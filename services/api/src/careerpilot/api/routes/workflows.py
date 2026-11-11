"""Workflows and workflow runs (contract Lane D)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...agent_workflows.runner import (WorkflowRunner, decide_approval, run_in_background,
                                       validate_definition)
from ...core.auth import current_user
from ...core.system.runs import run_to_dict
from ...db.models import Approval, Checkpoint, Workflow, WorkflowRun
from ...db.session import get_db

router = APIRouter()


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    definition: dict
    enabled: bool = True


class RunIn(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class ApproveIn(BaseModel):
    approve: bool
    comment: str | None = None


def _wf(w: Workflow) -> dict:
    return {"id": w.id, "name": w.name, "definition": w.definition, "enabled": w.enabled,
            "created_at": w.created_at.isoformat()}


@router.get("/workflows")
def list_workflows(db: Session = Depends(get_db), _=Depends(current_user)):
    rows = db.query(Workflow).filter(Workflow.deleted_at.is_(None)).order_by(Workflow.created_at)
    items = [_wf(w) for w in rows]
    return {"items": items, "total": len(items)}


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowIn, db: Session = Depends(get_db), _=Depends(current_user)):
    errs = validate_definition(body.definition)
    if errs:
        raise HTTPException(422, errs)
    w = Workflow(name=body.name, definition=body.definition, enabled=body.enabled)
    db.add(w)
    db.flush()
    return _wf(w)


@router.get("/workflows/{wid}")
def get_workflow(wid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    w = db.get(Workflow, wid)
    if not w or w.deleted_at:
        raise HTTPException(404, "Workflow not found")
    return _wf(w)


@router.post("/workflows/{wid}/run", status_code=202)
def run_workflow(wid: str, body: RunIn, bg: BackgroundTasks, db: Session = Depends(get_db),
                 _=Depends(current_user), idempotency_key: str | None = Header(None)):
    w = db.get(Workflow, wid)
    if not w or w.deleted_at:
        raise HTTPException(404, "Workflow not found")
    if not w.enabled:
        raise HTTPException(409, "workflow is disabled")
    runner = WorkflowRunner(db, None)
    run = runner.create(wid, body.inputs, idempotency_key)
    fresh = run.status == "pending"
    db.commit()
    if fresh:
        bg.add_task(run_in_background, "workflow", run.id)
    return run_to_dict(run)


def _get_run(db: Session, rid: str) -> WorkflowRun:
    r = db.get(WorkflowRun, rid)
    if not r or r.deleted_at or r.workflow_id is None or r.parent_run_id is not None:
        raise HTTPException(404, "Workflow run not found")
    return r


def _pending_approval(db: Session, rid: str) -> Approval | None:
    return (db.query(Approval).filter_by(subject_type="workflow_run", subject_id=rid,
                                         status="pending").order_by(Approval.created_at.desc())
            .first())


@router.get("/workflow-runs/{rid}")
def get_workflow_run(rid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    r = _get_run(db, rid)
    ap = _pending_approval(db, rid)
    kids = db.query(WorkflowRun).filter_by(parent_run_id=rid).order_by(WorkflowRun.created_at)
    return run_to_dict(r) | {
        "workflow_id": r.workflow_id, "retries": r.retries,
        "pending_approval": {"id": ap.id, "kind": ap.kind, "snapshot": ap.snapshot} if ap else None,
        "steps": [{"run_id": c.id, "agent": c.agent, "status": c.status, "retries": c.retries,
                   "key": c.idempotency_key} for c in kids]}


@router.get("/workflow-runs/{rid}/checkpoints")
def checkpoints(rid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    _get_run(db, rid)
    rows = sorted(db.query(Checkpoint).filter_by(run_id=rid).all(),
                  key=lambda c: (c.state or {}).get("seq", 0))
    return {"items": [{"id": c.id, "step": c.step, "seq": (c.state or {}).get("seq"),
                       "awaiting_approval": c.awaiting_approval,
                       "next_index": (c.state or {}).get("next_index"),
                       "outputs": list(((c.state or {}).get("outputs") or {}).keys()),
                       "created_at": c.created_at.isoformat()} for c in rows],
            "total": len(rows)}


@router.post("/workflow-runs/{rid}/approve", status_code=202)
def approve_run(rid: str, body: ApproveIn, bg: BackgroundTasks, db: Session = Depends(get_db),
                user=Depends(current_user)):
    _get_run(db, rid)
    ap = _pending_approval(db, rid)
    if ap is None:
        raise HTTPException(409, "run has no pending approval")
    decide_approval(db, ap.id, body.approve, user.username, body.comment)
    db.commit()
    if body.approve:
        bg.add_task(run_in_background, "resume", rid)
    return run_to_dict(db.get(WorkflowRun, rid))
