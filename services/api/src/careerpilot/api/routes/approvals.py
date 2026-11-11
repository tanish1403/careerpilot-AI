"""Approvals inbox + decision (contract Lane D). Submit approvals are delegated to Lane E's
applications service so snapshot-fingerprint checks stay identical to its grant-submit route."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...agent_workflows.runner import decide_approval, run_in_background
from ...applications import service as app_svc
from ...core.audit import audit
from ...core.auth import current_user
from ...db.base import utcnow
from ...db.models import Application, Approval
from ...db.session import get_db

router = APIRouter()


class DecideIn(BaseModel):
    grant: bool
    comment: str | None = None


def approval_out(a: Approval) -> dict:
    return {"id": a.id, "kind": a.kind, "subject_type": a.subject_type, "subject_id": a.subject_id,
            "status": a.status, "actor": a.actor, "snapshot": a.snapshot or {},
            "created_at": a.created_at.isoformat(),
            "decided_at": a.decided_at.isoformat() if a.decided_at else None}


@router.get("/approvals")
def list_approvals(status: str | None = None, kind: str | None = None, limit: int = 100,
                   offset: int = 0, db: Session = Depends(get_db), _=Depends(current_user)):
    q = db.query(Approval).filter(Approval.deleted_at.is_(None))
    if status:
        q = q.filter(Approval.status == status)
    if kind:
        q = q.filter(Approval.kind == kind)
    return {"items": [approval_out(a) for a in
                      q.order_by(Approval.created_at.desc()).offset(offset).limit(limit)],
            "total": q.count()}


@router.post("/approvals/{aid}/decide")
def decide(aid: str, body: DecideIn, bg: BackgroundTasks, db: Session = Depends(get_db),
           user=Depends(current_user)):
    ap = db.get(Approval, aid)
    if ap is None or ap.deleted_at:
        raise HTTPException(404, "Approval not found")
    if ap.status != "pending":
        raise HTTPException(409, f"Approval is {ap.status}, not pending")
    if ap.kind == "submit" and ap.subject_type == "application":
        app = db.get(Application, ap.subject_id)
        if app is None:
            raise HTTPException(404, "Application not found")
        try:
            app_svc.grant_submit(db, app, aid, user.username, body.grant)
        except app_svc.ApplicationError as e:
            db.commit()   # keep invalidation side effects
            raise HTTPException(e.status, e.detail) from None
    elif ap.subject_type == "workflow_run":
        decide_approval(db, aid, body.grant, user.username, body.comment)
        if body.grant:
            bg.add_task(run_in_background, "resume", ap.subject_id)
    else:   # resume / autofill etc: record the decision; consumers read the row
        ap.status, ap.actor, ap.decided_at = ("granted" if body.grant else "denied"), \
            user.username, utcnow()
        audit(db, "approval.decided", actor=user.username, subject_type="approval",
              subject_id=ap.id, detail={"grant": body.grant, "kind": ap.kind})
    db.commit()
    return approval_out(db.get(Approval, aid))
