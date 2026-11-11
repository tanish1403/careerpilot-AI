"""Dashboard aggregates. Tolerates empty tables and tables other lanes have not populated."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...core.features import FEATURES
from ...core.system.runs import iso
from ...db.base import utcnow
from ...db.models import Application, AuditEvent, Interview, Job, MatchResult, StudyTask
from ...db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(current_user)])


def _count(db: Session, model, *cond) -> int:
    live = model.deleted_at.is_(None)
    return db.execute(select(func.count()).select_from(model).where(live, *cond)).scalar_one()


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    by_state = dict(db.execute(select(Application.state, func.count()).where(
        Application.deleted_at.is_(None)).group_by(Application.state)).all())
    jobs = _count(db, Job)
    new_jobs = 0
    try:
        from datetime import timedelta
        new_jobs = _count(db, Job, Job.first_seen_at >= utcnow() - timedelta(days=7))
    except Exception:  # noqa: BLE001
        pass
    counts = {"jobs": jobs, "new_jobs": new_jobs, "applications": sum(by_state.values()),
              "by_state": by_state, "shortlisted": by_state.get("Shortlisted", 0)}

    upcoming: list[dict] = []
    for iv in db.execute(select(Interview).where(Interview.deleted_at.is_(None))
                         .order_by(Interview.created_at.desc()).limit(5)).scalars():
        upcoming.append({"type": "interview", "id": iv.id,
                         "title": getattr(iv, "title", None) or getattr(iv, "kind", "interview"),
                         "at": iso(getattr(iv, "scheduled_at", None))})
    for t in db.execute(select(StudyTask).where(StudyTask.deleted_at.is_(None))
                        .order_by(StudyTask.created_at.desc()).limit(5)).scalars():
        if getattr(t, "status", None) in (None, "todo", "pending", "open"):
            upcoming.append({"type": "study_task", "id": t.id,
                             "title": getattr(t, "title", "study task"),
                             "at": iso(getattr(t, "due_at", None))})
    for a in db.execute(select(Application).where(
            Application.deleted_at.is_(None), Application.follow_up_at.is_not(None))
            .order_by(Application.follow_up_at).limit(5)).scalars():
        upcoming.append({"type": "follow_up", "id": a.id, "title": "Application follow-up",
                         "at": iso(a.follow_up_at)})

    events = db.execute(select(AuditEvent).where(AuditEvent.deleted_at.is_(None))
                        .order_by(AuditEvent.created_at.desc()).limit(10)).scalars().all()
    recent = [{"id": e.id, "action": e.action, "subject_type": e.subject_type,
               "subject_id": e.subject_id, "created_at": iso(e.created_at)} for e in events]

    top = []
    rows = db.execute(select(MatchResult, Job).join(Job, Job.id == MatchResult.job_id).where(
        MatchResult.deleted_at.is_(None), Job.deleted_at.is_(None))
        .order_by(MatchResult.priority_score.desc()).limit(5)).all()
    for m, j in rows:
        top.append({"match_id": m.id, "job_id": j.id, "title": j.title,
                    "company_name": j.company_name, "eligibility": m.eligibility,
                    "fit_score": m.fit_score, "priority_score": m.priority_score})

    feature_status = {k: str(v["status"]) for k, v in FEATURES.items()}
    return {"counts": counts, "upcoming": upcoming, "recent_events": recent,
            "top_matches": top, "feature_status": feature_status}
