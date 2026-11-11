"""POST /runs/{id}/pause|resume|cancel (Lane D; Lane A's runs.py only has the read endpoints)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ...agent_workflows.runner import WorkflowRunner, latest_checkpoint, run_in_background
from ...core.auth import current_user
from ...core.system.runs import run_to_dict
from ...db.models import Approval, WorkflowRun
from ...db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(current_user)])


def _run(db: Session, rid: str) -> WorkflowRun:
    r = db.get(WorkflowRun, rid)
    if not r or r.deleted_at:
        raise HTTPException(404, "Run not found")
    return r


@router.post("/{rid}/pause")
def pause(rid: str, db: Session = Depends(get_db)):
    _run(db, rid)
    try:
        return run_to_dict(WorkflowRunner(db, None).pause(rid))
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/{rid}/cancel")
def cancel(rid: str, db: Session = Depends(get_db)):
    _run(db, rid)
    try:
        return run_to_dict(WorkflowRunner(db, None).cancel(rid))
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/{rid}/resume", status_code=202)
def resume(rid: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    r = _run(db, rid)
    if r.status != "paused":
        raise HTTPException(409, f"cannot resume a {r.status} run")
    cp = latest_checkpoint(db, rid)
    if cp is not None and cp.awaiting_approval:
        ap = db.get(Approval, cp.state.get("approval_id"))
        if ap is None or ap.status == "pending":
            raise HTTPException(409, "run is awaiting approval; decide the approval first")
    kind = "resume" if r.workflow_id and r.parent_run_id is None else "agent"
    if kind == "agent":
        r.status = "pending"
    db.commit()
    bg.add_task(run_in_background, kind, rid)
    return run_to_dict(r)
