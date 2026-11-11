"""Lane F: scheduler tasks/runs/status, digest, weekly report."""
from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.auth import current_user
from ...db.base import utcnow
from ...db.models import ScheduledTask, Setting, TaskRun
from ...db.session import get_db
from ...scheduler import service as svc
from ...scheduler import tasks as tasks_mod
from ..app import SHUTDOWN_HOOKS, STARTUP_HOOKS

router = APIRouter(tags=["scheduler"], dependencies=[Depends(current_user)])


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str
    cron: str = Field(min_length=9, max_length=100)
    timezone: str = "UTC"
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class TaskPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    config: dict | None = None


def _td(t: ScheduledTask) -> dict:
    return {"id": t.id, "name": t.name, "kind": t.kind, "cron": t.cron, "timezone": t.timezone,
            "enabled": t.enabled, "config": t.config or {},
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "next_run_at": (svc.get().next_runs().get(t.id) if t.enabled else None)}


def _rd(r: TaskRun) -> dict:
    return {"id": r.id, "task_id": r.task_id, "period_key": r.period_key, "status": r.status, "result": r.result or {},
            "error": r.error, "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def _task(db: Session, tid: str) -> ScheduledTask:
    t = db.get(ScheduledTask, tid)
    if t is None or t.deleted_at is not None:
        raise HTTPException(404, "task not found")
    return t


@router.get("/scheduler/tasks")
def list_tasks(db: Session = Depends(get_db)):
    return [_td(t) for t in db.query(ScheduledTask).filter(ScheduledTask.deleted_at.is_(None))
            .order_by(ScheduledTask.created_at)]


@router.post("/scheduler/tasks", status_code=201)
def create_task(body: TaskIn, db: Session = Depends(get_db)):
    try:
        svc.validate_task(body.kind, body.cron, body.timezone)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    t = ScheduledTask(**body.model_dump())
    db.add(t)
    db.commit()
    svc.notify_changed()
    return _td(t)


@router.patch("/scheduler/tasks/{tid}")
def patch_task(tid: str, body: TaskPatch, db: Session = Depends(get_db)):
    t = _task(db, tid)
    data = body.model_dump(exclude_unset=True)
    try:
        svc.validate_task(t.kind, data.get("cron", t.cron), data.get("timezone", t.timezone))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    svc.notify_changed()
    return _td(t)


@router.post("/scheduler/tasks/{tid}/run-now")
def run_now(tid: str, db: Session = Depends(get_db)):
    return _rd(svc.run_now(db, _task(db, tid)))


@router.post("/scheduler/runs/{rid}/retry")
def retry(rid: str, db: Session = Depends(get_db)):
    r = db.get(TaskRun, rid)
    if r is None:
        raise HTTPException(404, "run not found")
    if r.status != "failed":
        raise HTTPException(409, "only failed runs can be retried")
    return _rd(svc.execute(db, _task(db, r.task_id), r.period_key, retry=True))


@router.post("/scheduler/pause")
def pause(db: Session = Depends(get_db)):
    svc.set_paused(db, True)
    return status(db)


@router.post("/scheduler/resume")
def resume(db: Session = Depends(get_db)):
    svc.set_paused(db, False)
    return status(db)


@router.get("/scheduler/runs")
def runs(task_id: str | None = None, status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(TaskRun)
    if task_id:
        q = q.filter(TaskRun.task_id == task_id)
    if status:
        q = q.filter(TaskRun.status == status)
    return [_rd(r) for r in q.order_by(TaskRun.created_at.desc()).limit(min(limit, 500))]


@router.get("/scheduler/status")
def status(db: Session = Depends(get_db)):
    return {"running": svc.is_running(), "paused": svc.is_paused(db), "enabled_in_settings": get_settings().scheduler_enabled,
            "kinds": svc.kinds(), "tasks": db.query(ScheduledTask).filter(ScheduledTask.deleted_at.is_(None)).count(),
            "failed_runs": db.query(TaskRun).filter(TaskRun.status == "failed").count()}


@router.get("/digest/latest")
def digest_latest(db: Session = Depends(get_db)):
    row = db.get(Setting, "digest.latest")
    if row is None:
        raise HTTPException(404, "no digest generated yet")
    return row.value


@router.get("/reports/weekly")
def weekly(db: Session = Depends(get_db)):
    return tasks_mod.weekly_report(db, utcnow())


def _start(app: FastAPI) -> None:
    if get_settings().scheduler_enabled:
        svc.get().start()


def _stop(app: FastAPI) -> None:
    if svc.is_running():
        svc.get().stop()


if _start not in STARTUP_HOOKS:
    STARTUP_HOOKS.append(_start)
    SHUTDOWN_HOOKS.append(_stop)
