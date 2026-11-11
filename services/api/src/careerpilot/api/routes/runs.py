from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...core.system.runs import run_to_dict
from ...db.models import WorkflowRun
from ...db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(current_user)])


@router.get("")
def list_runs(status: str | None = None, agent: str | None = None,
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db)):
    cond = [WorkflowRun.deleted_at.is_(None)]
    if status:
        cond.append(WorkflowRun.status == status)
    if agent:
        cond.append(WorkflowRun.agent == agent)
    total = db.execute(select(func.count()).select_from(WorkflowRun).where(*cond)).scalar_one()
    rows = db.execute(select(WorkflowRun).where(*cond).order_by(WorkflowRun.created_at.desc())
                      .limit(limit).offset(offset)).scalars().all()
    return {"items": [run_to_dict(r) for r in rows], "total": total}


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(WorkflowRun, run_id)
    if not run or run.deleted_at is not None:
        raise HTTPException(404, "Run not found")
    return run_to_dict(run)
