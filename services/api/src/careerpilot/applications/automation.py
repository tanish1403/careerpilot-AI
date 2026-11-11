"""Orchestration of supervised autofill: DB-aware glue between applications and the browser layer.

Hard rules: only fields with status `ok` are filled; the final submit/apply click is NEVER performed
(there is no such code path) - the user always finishes in the browser themselves."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from ..browser_automation.adapters import (FieldMapping, FormField, UnsupportedFormError,
                                          get_adapter)
from ..browser_automation.allowlist import get_allowlist, is_allowed
from ..browser_automation.safety import Blocker, detect_blockers
from ..browser_automation.session import MANAGER, AutomationSession, BrowserUnavailable, BrowserWorker
from ..core.config import get_settings
from ..core.enums import ApplicationState as S
from ..core.redaction import redact_text
from ..db.models import Application, ResumeVersion, Setting
from . import service as svc
from .classifier import classify_question
from .service import ApplicationError

log = logging.getLogger("careerpilot.automation")
SESSION_STATES = (S.APPROVED.value, S.AUTOFILL_IN_PROGRESS.value)


def headed_default(db: Session) -> bool:
    row = db.get(Setting, "automation.headed")
    if row is not None and isinstance(row.value, bool):
        return row.value
    return os.environ.get("CAREERPILOT_AUTOMATION_HEADED", "").lower() in ("1", "true", "yes")


def get_session(sid: str) -> AutomationSession:
    s = MANAGER.get(sid)
    if s is None:
        raise ApplicationError(404, "Automation session not found (sessions do not survive a restart)")
    return s


def start_session(db: Session, application_id: str, actor: str,
                  headed: bool | None = None) -> AutomationSession:
    app = svc.get_app(db, application_id)
    if app.state not in SESSION_STATES:
        raise ApplicationError(409, f"Automation requires state Approved or AutofillInProgress "
                                    f"(current: {app.state})")
    url = app.destination_url or ""
    allow = get_allowlist(db)
    if not is_allowed(url, allow):
        raise ApplicationError(403, "Destination domain is not on the automation allowlist")
    if MANAGER.active_for(app.id) is not None:
        raise ApplicationError(409, "An automation session is already active for this application")
    worker = BrowserWorker(allow, headed if headed is not None else headed_default(db))
    try:
        worker.start()
    except BrowserUnavailable as e:
        worker.close()
        raise ApplicationError(503, f"Browser could not be launched: {e}") from None
    sess = AutomationSession(app.id, url, worker)
    sess.adapter_name = get_adapter(url).name
    MANAGER.add(sess)
    sess.blockers = [b.as_dict() for b in worker.goto(url)]
    svc.record_event(db, app, "automation_session_started", actor,
                     detail={"session_id": sess.id, "headed": worker.headed,
                             "adapter": sess.adapter_name,
                             "blockers": [b["kind"] for b in sess.blockers]})
    return sess


def _assess(sess: AutomationSession) -> tuple[list[Blocker], list[FormField]]:
    """Read-only inspection of the live page: hard blockers + extracted fields."""
    w = sess.worker
    blockers = w.call(lambda page: detect_blockers(page, []))
    for v in dict.fromkeys(w.violations):
        blockers.insert(0, Blocker("domain_not_allowed", v))
    if blockers:
        return blockers, []
    adapter = get_adapter(sess.url)
    sess.adapter = adapter
    sess.adapter_name = adapter.name
    try:
        fields = w.call(lambda page: adapter.extract_fields(page))
    except UnsupportedFormError as e:
        return [Blocker(getattr(e, "kind", "unsupported_form"), str(e))], []
    sess.fields = fields
    return [], fields


def _proposals(db: Session, app: Application, fields: list[FormField]) -> list[tuple[FieldMapping, dict]]:
    rv = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    out: list[tuple[FieldMapping, dict]] = []
    for f in fields:
        value, source, status, reason = None, "", "needs_user", f.reason
        if not f.supported:
            status = "unsupported"
        elif f.kind == "file":
            low = f.label.lower()
            if "resume" in low or low == "cv" or "curriculum" in low:
                p = Path(rv.pdf_path) if rv and rv.pdf_path else None
                if p and p.is_file():
                    value, source, status = str(p), f"approved resume v{rv.version_no}", "ok"
                else:
                    reason = "no compiled PDF for the approved resume"
            else:
                status, reason = "unsupported", "file upload other than the resume"
        else:
            cls = classify_question(f.label)
            if cls.sensitive:
                status, source = "sensitive", f"policy:{cls.category}"
                reason = "sensitive question: never auto-answered or auto-filled"
            else:
                row = svc.ensure_answers(db, app, [f.label], "system")[0]
                if row.sensitive:
                    status, source = "sensitive", "policy"
                elif (row.answer or "").strip() and (row.evidence_ids or row.user_confirmed):
                    value = row.answer
                    source = (f"profile facts {','.join(row.evidence_ids)}" if row.evidence_ids
                              else "user-confirmed answer")
                    status = "ok"
                    if f.kind in ("select", "radio") and f.options and not any(
                            o.strip().lower() == value.strip().lower() for o in f.options):
                        status, value, reason = "needs_user", None, "answer is not one of the options"
                else:
                    reason = "no confirmed answer"
        m = FieldMapping(f, value, status, source)
        out.append((m, {"label": f.label, "proposed_value": value if status == "ok" else None,
                        "source": source, "status": status, "kind": f.kind, "required": f.required,
                        "reason": reason}))
    return out


def preview(db: Session, sess: AutomationSession, actor: str) -> dict:
    app = svc.get_app(db, sess.application_id)
    _ensure_live(sess)
    blockers, fields = _assess(sess)
    sess.blockers = [b.as_dict() for b in blockers]
    if blockers:
        return {"fields": [], "blockers": sess.blockers}
    props = _proposals(db, app, fields)
    soft = [{"kind": "needs_user", "detail": p["label"], "hard": False}
            for _, p in props if p["required"] and p["status"] != "ok"]
    svc.record_event(db, app, "fill_preview", actor,
                     detail={"session_id": sess.id,
                             "fields": [{"label": p["label"], "status": p["status"]} for _, p in props]})
    return {"fields": [p for _, p in props], "blockers": soft}


def _ensure_live(sess: AutomationSession) -> None:
    if sess.status == "stopped" or sess.worker.closed:
        raise ApplicationError(409, "Automation session is closed")


def _block(db: Session, app: Application, sess: AutomationSession, blockers: list[Blocker],
           actor: str) -> dict:
    sess.status = "blocked"
    sess.blockers = [b.as_dict() for b in blockers]
    svc.record_event(db, app, "automation_blocked", actor,
                     detail={"session_id": sess.id, "blockers": sess.blockers})
    if app.state == S.APPROVED.value:
        svc.transition(db, app, S.AUTOFILL_IN_PROGRESS.value, actor, "autofill started", internal=True)
    svc.transition(db, app, S.BLOCKED.value, actor,
                   "; ".join(b.kind for b in blockers), internal=True)
    if not sess.worker.headed:
        sess.worker.close()
    return {"status": "blocked", "state": app.state, "blockers": sess.blockers, "fields": [],
            "screenshot": None}


def autofill(db: Session, sess: AutomationSession, actor: str) -> dict:
    app = svc.get_app(db, sess.application_id)
    _ensure_live(sess)
    if sess.status == "blocked":
        raise ApplicationError(409, "Session is blocked; stop it")
    if app.state not in SESSION_STATES:
        raise ApplicationError(409, f"Autofill requires Approved/AutofillInProgress "
                                    f"(current: {app.state})")
    if not is_allowed(sess.url, get_allowlist(db)):
        return _block(db, app, sess, [Blocker("domain_not_allowed", "destination no longer allowlisted")],
                      actor)
    blockers, fields = _assess(sess)
    if blockers:
        return _block(db, app, sess, blockers, actor)
    if app.state == S.APPROVED.value:
        svc.transition(db, app, S.AUTOFILL_IN_PROGRESS.value, actor, "autofill started", internal=True)
    props = _proposals(db, app, fields)
    mapping = [m for m, _ in props if m.status == "ok"]      # ONLY ok fields are ever filled
    adapter = sess.adapter
    results = sess.worker.call(lambda page: adapter.fill(page, mapping)) if mapping else []
    late = sess.worker.call(lambda page: detect_blockers(page, []))
    if late:                                                  # e.g. a challenge appeared after typing
        return _block(db, app, sess, late, actor)
    by_label = {r.label: r for r in results}
    shot = _capture_review(sess, props, by_label)
    rows, needs_user = [], []
    for m, p in props:
        r = by_label.get(m.field.label)
        rows.append({"label": p["label"], "status": p["status"], "filled": bool(r and r.status == "filled"),
                     "validated": bool(r and r.validated), "value": r.value if r else None,
                     "fill_status": r.status if r else "skipped", "located_via": r.via if r else None,
                     "detail": (r.detail if r and r.detail else p["reason"])})
        if p["status"] != "ok" or (r and not r.validated):
            needs_user.append({"kind": "needs_user", "detail": p["label"], "hard": False,
                               "status": p["status"] if p["status"] != "ok" else "validation_failed"})
    mismatches = [r.label for r in results if r.status != "filled"]
    svc.record_event(db, app, "autofill_completed", actor, detail={
        "session_id": sess.id, "screenshot": shot["screenshot"],
        "fields": [{"label": r["label"], "status": r["status"], "fill_status": r["fill_status"],
                    "validated": r["validated"]} for r in rows],
        "validation_failures": mismatches})
    svc.transition(db, app, S.USER_SUBMISSION_REVIEW.value, actor,
                   "autofill finished; awaiting user review and manual submission", internal=True)
    sess.status = "review"
    sess.blockers = needs_user
    sess.review = {**shot, "filled": sum(1 for r in rows if r["filled"]), "total": len(rows),
                   "validation_failures": mismatches}
    return {"status": "review", "state": app.state, "fields": rows, "blockers": needs_user,
            "screenshot": shot["screenshot"], "review": sess.review,
            "message": "Review the form in the browser and submit it yourself; "
                       "CareerPilot never clicks the final submit button."}


def _capture_review(sess: AutomationSession, props, by_label) -> dict:
    d = get_settings().artifacts_dir / "automation" / sess.id
    d.mkdir(parents=True, exist_ok=True)
    png = d / "review.png"
    sess.worker.call(lambda page: page.screenshot(path=str(png), full_page=True))
    summary = []
    for m, p in props:
        r = by_label.get(m.field.label)
        summary.append({"label": p["label"], "status": p["status"],
                        "filled": bool(r and r.status == "filled"),
                        "validated": bool(r and r.validated),
                        "value_preview": (redact_text(r.value)[:80] if r and r.value and p["status"] == "ok"
                                          else None)})
    (d / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"screenshot": f"automation/{sess.id}/review.png",
            "summary": f"automation/{sess.id}/summary.json"}


def stop_session(db: Session, sess: AutomationSession, actor: str) -> dict:
    app = svc.get_app(db, sess.application_id)
    sess.status = "stopped"
    sess.worker.close()
    svc.record_event(db, app, "automation_session_stopped", actor, detail={"session_id": sess.id})
    return sess.public()


def screenshot_path(sess: AutomationSession) -> Path | None:
    p = get_settings().artifacts_dir / "automation" / sess.id / "review.png"
    return p if p.is_file() else None
