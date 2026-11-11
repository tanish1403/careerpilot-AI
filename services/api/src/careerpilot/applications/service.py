"""Application lifecycle, answers, approvals and follow-ups.

Integrity rules enforced here (not in the routes):
* transitions obey core.enums.can_transition; `Submitted` and `Approved` are NOT reachable through
  the generic transition path (only confirm_submitted / approve_resume);
* every transition writes an ApplicationEvent and an audit event;
* a submit approval snapshots the exact resume version, final answers, destination URL and time;
  any later change to them invalidates the approval; confirm-submitted requires a granted approval
  whose snapshot still equals the current state;
* a second confirmation for an already-submitted application is refused.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.audit import audit
from ..core.enums import ApplicationState as S
from ..core.enums import TRANSITIONS, can_transition
from ..core.redaction import redact
from ..db.base import utcnow
from ..db.models import (Application, ApplicationAnswer, ApplicationEvent, Approval, Job,
                         ResumeVersion)
from .classifier import classify_question, normalize_question
from .facts import draft_answer

WS = "default"
GENERIC_BLOCKED_TARGETS = {S.SUBMITTED.value, S.APPROVED.value}
FOLLOW_UP_DAYS = 7
DEFAULT_QUESTIONS = ["Full name", "Email", "Phone", "Location", "LinkedIn profile",
                     "Website / portfolio", "GitHub profile", "Current company",
                     "Current job title"]


class ApplicationError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + ("+00:00" if dt.tzinfo is None else "")


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---- events ---------------------------------------------------------------------------------
def record_event(db: Session, app: Application, kind: str, actor: str | None, *,
                 from_state: str | None = None, to_state: str | None = None,
                 detail: dict | None = None) -> ApplicationEvent:
    ev = ApplicationEvent(application_id=app.id, kind=kind, from_state=from_state,
                          to_state=to_state, actor=actor, detail=redact(detail or {}))
    db.add(ev)
    audit(db, f"application.{kind}", actor=actor, subject_type="application", subject_id=app.id,
          detail={"from": from_state, "to": to_state, **(detail or {})})
    db.flush()
    return ev


def _fail(db: Session, status: int, detail: str, *, keep: bool = False):
    if keep:
        db.commit()  # persist invalidation/audit side effects made before refusing
    raise ApplicationError(status, detail)


# ---- lookup ---------------------------------------------------------------------------------
def get_app(db: Session, app_id: str) -> Application:
    a = db.get(Application, app_id)
    if a is None or a.deleted_at is not None:
        raise ApplicationError(404, "Application not found")
    return a


def get_app_for_job(db: Session, job_id: str) -> Application | None:
    return (db.query(Application).filter(Application.job_id == job_id,
                                         Application.deleted_at.is_(None)).first())


def create_application(db: Session, job_id: str, actor: str,
                       idempotency_key: str | None = None) -> tuple[Application, bool]:
    """Idempotent per job (DB-unique). Returns (application, created)."""
    job = db.get(Job, job_id)
    if job is None or job.deleted_at is not None:
        raise ApplicationError(404, "Job not found")
    if idempotency_key:
        prev = db.query(Application).filter(Application.idempotency_key == idempotency_key,
                                            Application.deleted_at.is_(None)).first()
        if prev is not None:
            if prev.job_id != job_id:
                raise ApplicationError(409, "Idempotency key already used for another job")
            return prev, False
    existing = get_app_for_job(db, job_id)
    if existing is not None:
        return existing, False
    app = Application(job_id=job_id, state=S.DISCOVERED.value, destination_url=job.canonical_url,
                      idempotency_key=(idempotency_key or None))
    try:
        with db.begin_nested():
            db.add(app)
            db.flush()
    except IntegrityError:
        again = get_app_for_job(db, job_id)
        if again is None:
            raise
        return again, False
    record_event(db, app, "created", actor, to_state=app.state, detail={"job_id": job_id})
    return app, True


# ---- state machine --------------------------------------------------------------------------
def generic_targets(state: str) -> list[str]:
    try:
        cur = S(state)
    except ValueError:
        return []
    return sorted(t.value for t in TRANSITIONS.get(cur, set())
                  if t.value not in GENERIC_BLOCKED_TARGETS)


def transition(db: Session, app: Application, to_state: str, actor: str, note: str | None = None,
               *, internal: bool = False, detail: dict | None = None) -> Application:
    try:
        dst = S(to_state)
    except ValueError:
        raise ApplicationError(422, f"Unknown state {to_state!r}") from None
    try:
        src = S(app.state)
    except ValueError:
        raise ApplicationError(409, f"Application is in unknown state {app.state!r}") from None
    if not internal:
        if dst == S.SUBMITTED:
            raise ApplicationError(409, "Submitted can only be reached via request-submit, a "
                                        "granted submit approval and confirm-submitted")
        if dst == S.APPROVED:
            raise ApplicationError(409, "Approved can only be reached via approve-resume")
    if not can_transition(src, dst):
        raise ApplicationError(409, f"Illegal transition {src.value} -> {dst.value}")
    app.state = dst.value
    db.flush()
    if dst not in (S.USER_SUBMISSION_REVIEW, S.SUBMITTED):
        invalidate_approvals(db, app, f"state changed to {dst.value}", actor)
    record_event(db, app, "transition", actor, from_state=src.value, to_state=dst.value,
                 detail={"note": note, **(detail or {})})
    return app


# ---- answers --------------------------------------------------------------------------------
def answer_dict(a: ApplicationAnswer) -> dict:
    return {"id": a.id, "application_id": a.application_id, "question": a.question,
            "answer": a.answer, "evidence_ids": a.evidence_ids or [], "sensitive": a.sensitive,
            "needs_user": a.needs_user, "user_confirmed": a.user_confirmed,
            "category": classify_question(a.question).category}


def list_answers(db: Session, app: Application) -> list[ApplicationAnswer]:
    return (db.query(ApplicationAnswer)
            .filter(ApplicationAnswer.application_id == app.id,
                    ApplicationAnswer.deleted_at.is_(None))
            .order_by(ApplicationAnswer.created_at, ApplicationAnswer.id).all())


def ensure_answers(db: Session, app: Application, questions: list[str],
                   actor: str) -> list[ApplicationAnswer]:
    """Create an answer row per question not already present, drafted from CONFIRMED facts only."""
    have = {normalize_question(a.question): a for a in list_answers(db, app)}
    out: list[ApplicationAnswer] = []
    for q in questions:
        key = normalize_question(q)
        if not key:
            continue
        if key in have:
            out.append(have[key])
            continue
        cls = classify_question(q)
        d = draft_answer(db, q, cls)
        row = ApplicationAnswer(application_id=app.id, question=" ".join(q.split())[:1000],
                                answer=d.answer, evidence_ids=d.evidence_ids,
                                sensitive=d.sensitive, needs_user=d.needs_user,
                                user_confirmed=False)
        db.add(row)
        db.flush()
        have[key] = row
        out.append(row)
        record_event(db, app, "answer_drafted", actor,
                     detail={"answer_id": row.id, "category": d.category, "source": d.source,
                             "needs_user": d.needs_user})
    return out


def update_answers(db: Session, app: Application, items: list[dict], actor: str) -> list[ApplicationAnswer]:
    changed = False
    for it in items:
        aid = it.get("id")
        text = it.get("answer")
        if aid:
            row = db.get(ApplicationAnswer, aid)
            if row is None or row.application_id != app.id or row.deleted_at is not None:
                raise ApplicationError(404, f"Answer {aid} not found")
        else:
            q = (it.get("question") or "").strip()
            if not q:
                raise ApplicationError(422, "question is required for a new answer")
            cls = classify_question(q)
            row = ApplicationAnswer(application_id=app.id, question=q[:1000], answer=None,
                                    evidence_ids=[], sensitive=cls.sensitive, needs_user=True)
            db.add(row)
            db.flush()
        if "answer" in it and (text or None) != row.answer:
            row.answer = (text or None)
            row.evidence_ids = []   # user-authored text is no longer backed by a profile fact
            row.user_confirmed = False
            row.needs_user = not bool(row.answer)
            changed = True
            record_event(db, app, "answer_edited", actor, detail={"answer_id": row.id})
        elif not aid:
            changed = True
    if changed:
        invalidate_approvals(db, app, "answers changed after approval was requested", actor)
    db.flush()
    return list_answers(db, app)


def confirm_answer(db: Session, answer_id: str, actor: str) -> ApplicationAnswer:
    row = db.get(ApplicationAnswer, answer_id)
    if row is None or row.deleted_at is not None:
        raise ApplicationError(404, "Answer not found")
    if not (row.answer or "").strip():
        raise ApplicationError(409, "Cannot confirm an empty answer; provide an answer first")
    row.user_confirmed = True
    row.needs_user = False
    db.flush()
    app = get_app(db, row.application_id)
    record_event(db, app, "answer_confirmed", actor,
                 detail={"answer_id": row.id, "sensitive": row.sensitive})
    return row


def unresolved_answers(db: Session, app: Application) -> list[ApplicationAnswer]:
    """Answers that still need the user: sensitive/needs_user and not confirmed."""
    return [a for a in list_answers(db, app)
            if (a.sensitive or a.needs_user or not (a.answer or "").strip()) and not a.user_confirmed]


# ---- approvals ------------------------------------------------------------------------------
def current_state_snapshot(db: Session, app: Application) -> dict:
    return {"application_id": app.id, "job_id": app.job_id,
            "resume_version_id": app.resume_version_id,
            "answers": sorted(({"id": a.id, "question": a.question, "answer": a.answer}
                               for a in list_answers(db, app)), key=lambda x: x["id"]),
            "destination_url": app.destination_url}


def fingerprint(snap: dict) -> str:
    core = {k: snap.get(k) for k in ("application_id", "job_id", "resume_version_id", "answers",
                                     "destination_url")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def _approvals(db: Session, app: Application, kind: str, statuses: tuple[str, ...]) -> list[Approval]:
    return (db.query(Approval).filter(Approval.subject_type == "application",
                                      Approval.subject_id == app.id, Approval.kind == kind,
                                      Approval.status.in_(statuses),
                                      Approval.deleted_at.is_(None))
            .order_by(Approval.created_at).all())


def invalidate_approvals(db: Session, app: Application, reason: str, actor: str | None) -> int:
    """Expire pending/granted submit approvals (their snapshot no longer matches reality)."""
    rows = _approvals(db, app, "submit", ("pending", "granted"))
    for ap in rows:
        ap.status = "expired"
        ap.snapshot = {**(ap.snapshot or {}), "invalidated_reason": reason,
                       "invalidated_at": utcnow().isoformat()}
        record_event(db, app, "approval_invalidated", actor,
                     detail={"approval_id": ap.id, "reason": reason})
    return len(rows)


def approve_resume(db: Session, app: Application, resume_version_id: str, actor: str) -> Approval:
    if app.state != S.REVIEW_REQUIRED.value:
        raise ApplicationError(409, f"Resume can only be approved in ReviewRequired "
                                    f"(current: {app.state})")
    rv = db.get(ResumeVersion, resume_version_id)
    if rv is None or rv.deleted_at is not None:
        raise ApplicationError(404, "Resume version not found")
    if rv.job_id not in (None, app.job_id):
        raise ApplicationError(409, "Resume version belongs to a different job")
    now = utcnow()
    prior = app.resume_version_id
    app.resume_version_id = rv.id
    app.approved_by, app.approved_at = actor, now
    ap = Approval(kind="resume", subject_type="application", subject_id=app.id, status="granted",
                  actor=actor, decided_at=now,
                  snapshot={"resume_version_id": rv.id, "version_no": rv.version_no,
                            "approved_at": now.isoformat()})
    db.add(ap)
    db.flush()
    if prior != rv.id:
        invalidate_approvals(db, app, "resume version changed", actor)
    record_event(db, app, "resume_approved", actor,
                 detail={"approval_id": ap.id, "resume_version_id": rv.id})
    transition(db, app, S.APPROVED.value, actor, "resume approved", internal=True)
    return ap


def request_submit(db: Session, app: Application, actor: str) -> Approval:
    if app.state != S.USER_SUBMISSION_REVIEW.value:
        raise ApplicationError(409, f"Submit approval can only be requested in "
                                    f"UserSubmissionReview (current: {app.state})")
    if app.submitted_at is not None:
        raise ApplicationError(409, "Application already submitted")
    if not app.resume_version_id:
        raise ApplicationError(409, "No approved resume version on this application")
    open_q = unresolved_answers(db, app)
    if open_q:
        raise ApplicationError(409, f"{len(open_q)} answer(s) still need your input or confirmation")
    snap = current_state_snapshot(db, app)
    fp = fingerprint(snap)
    for ap in _approvals(db, app, "submit", ("pending", "granted")):
        if (ap.snapshot or {}).get("fingerprint") == fp:
            return ap
    invalidate_approvals(db, app, "superseded by a new submit request", actor)
    ap = Approval(kind="submit", subject_type="application", subject_id=app.id, status="pending",
                  actor=actor,
                  snapshot={**snap, "fingerprint": fp, "requested_at": utcnow().isoformat()})
    db.add(ap)
    db.flush()
    record_event(db, app, "submit_requested", actor, detail={"approval_id": ap.id})
    return ap


def grant_submit(db: Session, app: Application, approval_id: str, actor: str,
                 granted: bool = True) -> Approval:
    """Human decision on a submit approval (stop-gap for Lane D's approvals route)."""
    ap = db.get(Approval, approval_id)
    if (ap is None or ap.kind != "submit" or ap.subject_type != "application"
            or ap.subject_id != app.id):
        raise ApplicationError(404, "Submit approval not found for this application")
    if ap.status != "pending":
        raise ApplicationError(409, f"Approval is {ap.status}, not pending")
    if (ap.snapshot or {}).get("fingerprint") != fingerprint(current_state_snapshot(db, app)):
        invalidate_approvals(db, app, "state changed before the approval was granted", actor)
        _fail(db, 409, "Approval snapshot no longer matches the application; request again",
              keep=True)
    ap.status = "granted" if granted else "denied"
    ap.actor, ap.decided_at = actor, utcnow()
    db.flush()
    record_event(db, app, "submit_approval_" + ap.status, actor, detail={"approval_id": ap.id})
    return ap


def confirm_submitted(db: Session, app: Application, approval_id: str, actor: str,
                      confirmation_ref: str | None = None) -> Application:
    """Record that the USER submitted the application manually. Never submits anything itself."""
    if app.state == S.SUBMITTED.value or app.submitted_at is not None:
        raise ApplicationError(409, "Application is already submitted (duplicate submission refused)")
    if app.state != S.USER_SUBMISSION_REVIEW.value:
        raise ApplicationError(409, f"Cannot confirm submission from state {app.state}")
    ap = db.get(Approval, approval_id)
    if (ap is None or ap.kind != "submit" or ap.subject_type != "application"
            or ap.subject_id != app.id or ap.deleted_at is not None):
        raise ApplicationError(409, "A granted submit approval for this application is required")
    if ap.status != "granted":
        raise ApplicationError(409, f"Submit approval is {ap.status}; a granted approval is required")
    snap = ap.snapshot or {}
    if snap.get("fingerprint") != fingerprint(current_state_snapshot(db, app)):
        invalidate_approvals(db, app, "state differs from the approved snapshot", actor)
        _fail(db, 409, "Application changed after approval; approval invalidated", keep=True)
    now = utcnow()
    res = db.execute(update(Application).where(Application.id == app.id,
                                               Application.state == S.USER_SUBMISSION_REVIEW.value,
                                               Application.submitted_at.is_(None))
                     .values(state=S.SUBMITTED.value, submitted_at=now,
                             submission_approval_id=ap.id))
    if res.rowcount != 1:
        raise ApplicationError(409, "Application was already submitted (concurrent confirmation)")
    db.refresh(app)
    app.confirmation_ref = (confirmation_ref or "").strip()[:500] or None
    if app.follow_up_at is None:
        app.follow_up_at = now + timedelta(days=FOLLOW_UP_DAYS)
    db.flush()
    record_event(db, app, "transition", actor, from_state=S.USER_SUBMISSION_REVIEW.value,
                 to_state=S.SUBMITTED.value,
                 detail={"approval_id": ap.id, "has_confirmation_ref": bool(app.confirmation_ref),
                         "destination_url": app.destination_url})
    return app


# ---- follow-ups / notes ----------------------------------------------------------------------
def update_meta(db: Session, app: Application, actor: str, *, notes: Any = ..., follow_up_at: Any = ...,
                confirmation_ref: Any = ...) -> Application:
    detail: dict = {}
    if notes is not ...:
        app.notes = notes or None
        detail["notes"] = True
    if follow_up_at is not ...:
        app.follow_up_at = _aware(follow_up_at)
        detail["follow_up_at"] = iso(app.follow_up_at)
    if confirmation_ref is not ...:
        if app.state not in (S.SUBMITTED.value, S.ASSESSMENT.value, S.INTERVIEW.value, S.OFFER.value):
            raise ApplicationError(409, "Confirmation reference can only be recorded after submission")
        app.confirmation_ref = (confirmation_ref or "").strip()[:500] or None
        detail["confirmation_ref"] = True
    db.flush()
    record_event(db, app, "updated", actor, detail=detail)
    return app


def due_follow_ups(db: Session, now: datetime | None = None) -> list[Application]:
    now = now or utcnow()
    rows = (db.query(Application).filter(Application.deleted_at.is_(None),
                                         Application.follow_up_at.is_not(None)).all())
    live = (S.SUBMITTED.value, S.ASSESSMENT.value, S.INTERVIEW.value)
    return sorted((a for a in rows if a.state in live and _aware(a.follow_up_at) <= now),
                  key=lambda a: _aware(a.follow_up_at))


# ---- views -------------------------------------------------------------------------------------
def base_dict(a: Application) -> dict:
    return {"id": a.id, "job_id": a.job_id, "state": a.state,
            "resume_version_id": a.resume_version_id, "approved_by": a.approved_by,
            "approved_at": iso(a.approved_at), "submitted_at": iso(a.submitted_at),
            "submission_approval_id": a.submission_approval_id,
            "confirmation_ref": a.confirmation_ref, "destination_url": a.destination_url,
            "notes": a.notes, "follow_up_at": iso(a.follow_up_at), "created_at": iso(a.created_at),
            "updated_at": iso(a.updated_at)}


def event_dict(e: ApplicationEvent) -> dict:
    return {"id": e.id, "kind": e.kind, "from_state": e.from_state, "to_state": e.to_state,
            "actor": e.actor, "detail": e.detail or {}, "created_at": iso(e.created_at)}


def list_events(db: Session, app: Application) -> list[ApplicationEvent]:
    return (db.query(ApplicationEvent).filter(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.created_at, ApplicationEvent.id).all())


def compute_blockers(db: Session, app: Application, allowlist: list[str]) -> list[dict]:
    from ..browser_automation.allowlist import is_allowed
    out: list[dict] = []
    n = len(unresolved_answers(db, app))
    if n and app.state in (S.RESUME_PREPARED.value, S.REVIEW_REQUIRED.value, S.APPROVED.value,
                           S.AUTOFILL_IN_PROGRESS.value, S.USER_SUBMISSION_REVIEW.value):
        out.append({"kind": "answers_need_user", "detail": f"{n} answer(s) need your input"})
    if not app.resume_version_id and app.state in (S.RESUME_PREPARED.value, S.REVIEW_REQUIRED.value):
        out.append({"kind": "resume_not_approved", "detail": "No resume version approved yet"})
    if app.state in (S.APPROVED.value, S.AUTOFILL_IN_PROGRESS.value):
        if not app.destination_url or not is_allowed(app.destination_url, allowlist):
            out.append({"kind": "domain_not_allowlisted",
                        "detail": "Destination domain is not on the automation allowlist; "
                                  "fill the form manually or add the domain"})
    if app.state == S.BLOCKED.value:
        for e in reversed(list_events(db, app)):
            if e.kind == "automation_blocked":
                out.extend((e.detail or {}).get("blockers", []))
                break
    if app.state == S.USER_SUBMISSION_REVIEW.value:
        pend = _approvals(db, app, "submit", ("pending",))
        if pend:
            out.append({"kind": "awaiting_submit_approval", "detail": "Submit approval pending"})
    return out


def detail_dict(db: Session, app: Application, allowlist: list[str]) -> dict:
    job = db.get(Job, app.job_id)
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    d = base_dict(app)
    d.update({
        "job": ({"id": job.id, "title": job.title, "company_name": job.company_name,
                 "location": job.location, "canonical_url": job.canonical_url} if job else None),
        "resume_version": ({"id": rv.id, "version_no": rv.version_no, "label": rv.label,
                            "job_id": rv.job_id, "created_at": iso(rv.created_at)} if rv else None),
        "answers": [answer_dict(a) for a in list_answers(db, app)],
        "events": [event_dict(e) for e in list_events(db, app)],
        "allowed_transitions": generic_targets(app.state),
        "blockers": compute_blockers(db, app, allowlist),
        "submit_approval": next(({"id": a.id, "status": a.status}
                                 for a in reversed(_approvals(db, app, "submit",
                                                              ("pending", "granted", "expired")))), None),
    })
    return d


def kanban(db: Session) -> dict:
    rows = (db.query(Application, Job).join(Job, Job.id == Application.job_id)
            .filter(Application.deleted_at.is_(None)).order_by(Application.updated_at.desc()).all())
    cols = {s.value: [] for s in S}
    for a, j in rows:
        cols.setdefault(a.state, []).append(
            {"id": a.id, "job_id": a.job_id, "title": j.title, "company_name": j.company_name,
             "state": a.state, "follow_up_at": iso(a.follow_up_at), "updated_at": iso(a.updated_at)})
    return {"columns": [{"state": s, "items": items} for s, items in cols.items()]}


def list_applications(db: Session, state: str | None = None) -> list[dict]:
    q = db.query(Application, Job).join(Job, Job.id == Application.job_id).filter(
        Application.deleted_at.is_(None))
    if state:
        q = q.filter(Application.state == state)
    out = []
    for a, j in q.order_by(Application.updated_at.desc()).all():
        d = base_dict(a)
        d["job"] = {"id": j.id, "title": j.title, "company_name": j.company_name}
        out.append(d)
    return out
