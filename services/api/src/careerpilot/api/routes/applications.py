"""Lane E: application center routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...applications import service as svc
from ...applications.service import DEFAULT_QUESTIONS, ApplicationError
from ...browser_automation.allowlist import get_allowlist
from ...core.auth import current_user
from ...core.enums import ApplicationState as S
from ...core.system.runs import fail_run, finish_run, mark_running, start_run
from ...db.models import ResumeVersion, User
from ...db.session import get_db, session_scope

router = APIRouter(tags=["applications"])


def http(e: ApplicationError) -> HTTPException:
    return HTTPException(e.status, e.detail)


class CreateBody(BaseModel):
    job_id: str
    idempotency_key: str | None = None


class TransitionBody(BaseModel):
    to_state: str
    note: str | None = None


class ApproveResumeBody(BaseModel):
    resume_version_id: str


class ConfirmBody(BaseModel):
    approval_id: str
    confirmation_ref: str | None = None


class PatchBody(BaseModel):
    notes: str | None = None
    follow_up_at: datetime | None = None
    confirmation_ref: str | None = None


def _call(fn, *a, **kw):  # noqa: ANN001
    try:
        return fn(*a, **kw)
    except ApplicationError as e:
        raise http(e) from None


@router.get("/applications")
def list_apps(state: str | None = None, db: Session = Depends(get_db),
              _: User = Depends(current_user)):
    return svc.list_applications(db, state)


@router.post("/applications")
def create_app(body: CreateBody, response: Response, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    app, created = _call(svc.create_application, db, body.job_id, user.username, body.idempotency_key)
    response.status_code = 201 if created else 200
    return {**svc.base_dict(app), "created": created}


@router.get("/applications/kanban")
def kanban(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return svc.kanban(db)


@router.get("/applications/follow-ups")
def follow_ups(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [svc.base_dict(a) for a in svc.due_follow_ups(db)]


@router.get("/applications/{app_id}")
def get_app(app_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    return svc.detail_dict(db, app, get_allowlist(db))


@router.patch("/applications/{app_id}")
def patch_app(app_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    kw: dict = {}
    parsed = PatchBody.model_validate({k: v for k, v in body.items() if k in PatchBody.model_fields})
    for k in ("notes", "follow_up_at", "confirmation_ref"):
        if k in body:
            kw[k] = getattr(parsed, k)
    _call(svc.update_meta, db, app, user.username, **kw)
    return svc.detail_dict(db, app, get_allowlist(db))


@router.post("/applications/{app_id}/transition")
def transition(app_id: str, body: TransitionBody, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    _call(svc.transition, db, app, body.to_state, user.username, body.note)
    return svc.detail_dict(db, app, get_allowlist(db))


@router.post("/applications/{app_id}/prepare", status_code=202)
def prepare(app_id: str, bg: BackgroundTasks, body: dict[str, Any] | None = Body(default=None),
            db: Session = Depends(get_db), user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    extra = [str(q) for q in ((body or {}).get("questions") or [])][:60]
    run = start_run(db, "application_prepare", {"application_id": app.id, "questions": len(extra)},
                    status="pending")
    db.commit()
    run_id, actor, aid = run.id, user.username, app.id

    def _exec() -> None:
        with session_scope() as s:
            mark_running(s, s.get(type(run), run_id))
        try:
            with session_scope() as s:
                out = _prepare_work(s, aid, extra, actor)
            with session_scope() as s:
                finish_run(s, s.get(type(run), run_id), output_refs=out)
        except Exception as e:  # noqa: BLE001
            with session_scope() as s:
                fail_run(s, s.get(type(run), run_id), e)
    bg.add_task(_exec)
    return {"run_id": run_id, "status": "pending", "application_id": aid}


def _prepare_work(db: Session, app_id: str, extra: list[str], actor: str) -> dict:
    app = svc.get_app(db, app_id)
    rows = svc.ensure_answers(db, app, DEFAULT_QUESTIONS + extra, actor)
    rv = (db.query(ResumeVersion).filter(ResumeVersion.job_id == app.job_id,
                                         ResumeVersion.deleted_at.is_(None))
          .order_by(ResumeVersion.created_at.desc()).first())
    advanced = False
    if rv is not None and app.state in (S.SHORTLISTED.value, S.NEEDS_EDIT.value):
        svc.transition(db, app, S.RESUME_PREPARED.value, actor, "resume available", internal=True)
        svc.transition(db, app, S.REVIEW_REQUIRED.value, actor, "ready for review", internal=True)
        advanced = True
    return {"answers": len(rows), "needs_user": sum(1 for r in rows if r.needs_user),
            "resume_version_id": rv.id if rv else None, "resume_missing": rv is None,
            "advanced_to_review": advanced}


@router.get("/applications/{app_id}/answers")
def get_answers(app_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    return [svc.answer_dict(a) for a in svc.list_answers(db, app)]


@router.put("/applications/{app_id}/answers")
def put_answers(app_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    items = body.get("answers")
    if not isinstance(items, list):
        raise HTTPException(422, "body must be {answers: [{id?, question?, answer}]}")
    rows = _call(svc.update_answers, db, app, items, user.username)
    return [svc.answer_dict(a) for a in rows]


@router.post("/answers/{answer_id}/confirm")
def confirm_answer(answer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.answer_dict(_call(svc.confirm_answer, db, answer_id, user.username))


@router.post("/applications/{app_id}/approve-resume")
def approve_resume(app_id: str, body: ApproveResumeBody, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    ap = _call(svc.approve_resume, db, app, body.resume_version_id, user.username)
    d = svc.detail_dict(db, app, get_allowlist(db))
    d["approval"] = {"id": ap.id, "kind": ap.kind, "status": ap.status}
    return d


def _approval(ap) -> dict:  # noqa: ANN001
    return {"id": ap.id, "kind": ap.kind, "status": ap.status, "snapshot": ap.snapshot,
            "actor": ap.actor, "decided_at": svc.iso(ap.decided_at)}


@router.post("/applications/{app_id}/request-submit", status_code=201)
def request_submit(app_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    return _approval(_call(svc.request_submit, db, app, user.username))


@router.post("/applications/{app_id}/grant-submit")
def grant_submit(app_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """Stop-gap human decision on a submit approval (see docs/LANE_E_NOTES.md)."""
    app = _call(svc.get_app, db, app_id)
    ap = _call(svc.grant_submit, db, app, str(body.get("approval_id", "")), user.username,
               bool(body.get("granted", True)))
    return _approval(ap)


@router.post("/applications/{app_id}/confirm-submitted")
def confirm_submitted(app_id: str, body: ConfirmBody, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    app = _call(svc.get_app, db, app_id)
    _call(svc.confirm_submitted, db, app, body.approval_id, user.username, body.confirmation_ref)
    return svc.detail_dict(db, app, get_allowlist(db))
