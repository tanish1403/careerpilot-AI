"""Lane F: study plans, tasks, resources, skill gaps, progress."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.base import utcnow
from ...db.models import LearningResource, StudyPlan, StudyTask
from ...db.session import get_db
from ...learning import service as svc

router = APIRouter(tags=["learning"], dependencies=[Depends(current_user)])


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    track: str | None = None
    hours_per_week: float | None = Field(default=None, gt=0, le=100)
    motivation: dict = Field(default_factory=dict)


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    track: str | None = None
    hours_per_week: float | None = Field(default=None, gt=0, le=100)
    motivation: dict | None = None
    replan: bool = False


class GenerateIn(BaseModel):
    tracks: list[str] = Field(default_factory=list)
    hours_per_week: float = Field(default=6.0, gt=0, le=100)
    job_ids: list[str] | None = None
    name: str | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    topic: str | None = None
    due_at: datetime | None = None
    reason: str | None = None
    resource_id: str | None = None
    hours: float | None = Field(default=None, gt=0)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    topic: str | None = None
    due_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(todo|in_progress|done|skipped)$")
    reason: str | None = None
    resource_id: str | None = None
    review_quality: int | None = Field(default=None, ge=0, le=5)


class ResourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=8, max_length=1000, pattern=r"^https?://")
    topic: str | None = None
    accessed_on: str | None = None


def _plan(db: Session, pid: str) -> StudyPlan:
    p = db.get(StudyPlan, pid)
    if p is None or p.deleted_at is not None:
        raise HTTPException(404, "study plan not found")
    return p


def _task(db: Session, tid: str) -> StudyTask:
    t = db.get(StudyTask, tid)
    if t is None or t.deleted_at is not None:
        raise HTTPException(404, "study task not found")
    return t


@router.get("/study-plans")
def list_plans(db: Session = Depends(get_db)):
    return [svc.plan_dict(db, p) for p in db.query(StudyPlan).filter(StudyPlan.deleted_at.is_(None))
            .order_by(StudyPlan.created_at.desc()).all()]


@router.post("/study-plans", status_code=201)
def create_plan(body: PlanIn, db: Session = Depends(get_db)):
    p = StudyPlan(**body.model_dump())
    db.add(p)
    db.flush()
    return svc.plan_dict(db, p, True)


@router.post("/study-plans/generate", status_code=201)
def generate(body: GenerateIn, db: Session = Depends(get_db)):
    try:
        p = svc.generate_plan(db, body.tracks, body.hours_per_week, body.job_ids, body.name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return svc.plan_dict(db, p, True)


@router.get("/study-plans/{pid}")
def get_plan(pid: str, db: Session = Depends(get_db)):
    return svc.plan_dict(db, _plan(db, pid), True)


@router.patch("/study-plans/{pid}")
def patch_plan(pid: str, body: PlanPatch, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    for k, v in body.model_dump(exclude_unset=True, exclude={"replan"}).items():
        setattr(p, k, v)
    out = svc.plan_dict(db, p, False)
    if body.replan:
        out["replan"] = svc.replan(db, p)
    db.flush()
    return {**out, **{"tasks": svc.plan_dict(db, p, True)["tasks"]}}


@router.post("/study-plans/{pid}/replan")
def replan(pid: str, hours_per_week: float | None = None, db: Session = Depends(get_db)):
    p = _plan(db, pid)
    return {"replan": svc.replan(db, p, hours_per_week), "plan": svc.plan_dict(db, p, True)}


@router.delete("/study-plans/{pid}", status_code=204)
def delete_plan(pid: str, db: Session = Depends(get_db)):
    _plan(db, pid).deleted_at = utcnow()


@router.get("/study-plans/{pid}/tasks")
def list_tasks(pid: str, db: Session = Depends(get_db)):
    return svc.plan_dict(db, _plan(db, pid), True)["tasks"]


@router.post("/study-plans/{pid}/tasks", status_code=201)
def add_task(pid: str, body: TaskIn, db: Session = Depends(get_db)):
    _plan(db, pid)
    data = body.model_dump(exclude={"hours"})
    t = StudyTask(plan_id=pid, **data)
    db.add(t)
    db.flush()
    if body.hours:
        svc.set_meta(db, t.id, {"hours": body.hours})
    return svc.task_dict(db, t)


@router.patch("/study-tasks/{tid}")
def patch_task(tid: str, body: TaskPatch, db: Session = Depends(get_db)):
    t = _task(db, tid)
    data = body.model_dump(exclude_unset=True, exclude={"review_quality"})
    for k, v in data.items():
        setattr(t, k, v)
    if body.review_quality is not None:
        svc.record_review(db, t, body.review_quality)
    elif data.get("status") == "done" and t.revise_at is None:
        svc.record_review(db, t, 4)   # first revision scheduled when a task is completed
    db.flush()
    return svc.task_dict(db, t)


@router.get("/study-plans/{pid}/export", response_class=PlainTextResponse)
def export(pid: str, db: Session = Depends(get_db)):
    return PlainTextResponse(svc.export_markdown(db, _plan(db, pid)), media_type="text/markdown")


@router.get("/learning/templates")
def templates():
    return list(svc.templates().values())


@router.get("/learning/resources")
def resources(db: Session = Depends(get_db)):
    return svc.resources(db)


@router.post("/learning/resources", status_code=201)
def add_resource(body: ResourceIn, db: Session = Depends(get_db)):
    r = LearningResource(title=body.title, url=body.url, topic=body.topic,
                         accessed_on=body.accessed_on or utcnow().date().isoformat())
    db.add(r)
    db.flush()
    return {"id": r.id, "title": r.title, "url": r.url, "topic": r.topic, "accessed_on": r.accessed_on,
            "origin": "user"}


@router.get("/learning/skill-gaps")
def skill_gaps(db: Session = Depends(get_db)):
    return svc.skill_gaps(db)


@router.get("/learning/revisions/due")
def revisions_due(db: Session = Depends(get_db)):
    return [svc.task_dict(db, t) for t in svc.due_revisions(db)]


@router.get("/learning/progress")
def progress(db: Session = Depends(get_db)):
    return svc.progress(db)
