"""Scheduled task handlers. There is deliberately NO submit/apply/autofill-capable kind: the scheduler can
only scan, summarise, remind and report. `assert_no_submit_kind` is enforced at import time and in tests."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import (Application, ApplicationEvent, Approval, Job, MatchResult, Notification, ScheduledTask,
                         Setting, StudyTask, TaskRun, InterviewSession)

FORBIDDEN_KIND_WORDS = ("submit", "apply", "autofill", "auto_fill", "send_application", "browser")
TERMINAL_APP = ("Submitted", "Rejected", "Cancelled", "Offer")


def assert_no_submit_kind(kinds) -> None:
    bad = [k for k in kinds if any(w in k for w in FORBIDDEN_KIND_WORDS)]
    assert not bad, f"scheduler must not expose submit-capable kinds: {bad}"


def _set(db: Session, key: str, value: dict) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def _notify(db: Session, kind: str, title: str, body: str, payload: dict) -> Notification:
    n = Notification(kind=kind, title=title, body=body, payload=payload)
    db.add(n)
    db.flush()
    return n


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def job_scan(db: Session, task: ScheduledTask, now: datetime) -> dict:
    from ..job_connectors import service as conn
    from ..matching.service import NoProfileError, score_all
    logs = conn.run_all_sources(db)
    out = {"sources_run": len(logs), "failed_sources": sum(1 for lg in logs if lg.status == "failed"),
           "created": sum(lg.created for lg in logs), "updated": sum(lg.updated for lg in logs)}
    try:
        res = score_all(db)
        out["scored"] = res.get("scored", res.get("count")) if isinstance(res, dict) else None
    except NoProfileError:
        out["scored"] = 0
        out["warning"] = "no profile: scoring skipped"
    return out


def build_digest(db: Session, now: datetime) -> dict:
    since = now - timedelta(hours=24)
    jobs = [j for j in db.query(Job).filter(Job.deleted_at.is_(None)).all()
            if _aware(j.first_seen_at) and _aware(j.first_seen_at) >= since]
    top = (db.query(MatchResult, Job).join(Job, Job.id == MatchResult.job_id)
           .filter(MatchResult.deleted_at.is_(None), Job.deleted_at.is_(None),
                   MatchResult.eligibility != "not_satisfied")
           .order_by(MatchResult.priority_score.desc()).limit(5).all())
    study = [t for t in db.query(StudyTask).filter(StudyTask.deleted_at.is_(None),
                                                   StudyTask.status.notin_(["done", "skipped"])).all()
             if t.due_at and _aware(t.due_at) <= now + timedelta(days=1)]
    revs = [t for t in db.query(StudyTask).filter(StudyTask.deleted_at.is_(None)).all()
            if t.revise_at and _aware(t.revise_at) <= now]
    fups = [a for a in db.query(Application).filter(Application.deleted_at.is_(None),
                                                    Application.state.notin_(TERMINAL_APP)).all()
            if a.follow_up_at and _aware(a.follow_up_at) <= now + timedelta(days=1)]
    return {"generated_at": now.isoformat(),
            "new_jobs": {"count": len(jobs), "items": [{"id": j.id, "title": j.title, "company": j.company_name}
                                                       for j in jobs[:5]]},
            "top_matches": [{"job_id": j.id, "title": j.title, "company": j.company_name, "fit_score": m.fit_score,
                             "priority_score": m.priority_score, "eligibility": m.eligibility} for m, j in top],
            "study_due": [{"id": t.id, "title": t.title, "due_at": t.due_at.isoformat()} for t in study[:10]],
            "revisions_due": [{"id": t.id, "title": t.title} for t in revs[:10]],
            "follow_ups_due": [{"application_id": a.id, "job_id": a.job_id, "state": a.state} for a in fups],
            "pending_approvals": db.query(Approval).filter(Approval.status == "pending",
                                                           Approval.deleted_at.is_(None)).count(),
            "failed_task_runs_24h": db.query(TaskRun).filter(TaskRun.status == "failed",
                                                             TaskRun.created_at >= since).count()}


def daily_digest(db: Session, task: ScheduledTask, now: datetime) -> dict:
    d = build_digest(db, now)
    _set(db, "digest.latest", d)
    body = (f"{d['new_jobs']['count']} new jobs, {len(d['top_matches'])} top matches, {len(d['study_due'])} study "
            f"tasks due, {len(d['revisions_due'])} revisions due, {len(d['follow_ups_due'])} follow-ups, "
            f"{d['pending_approvals']} approvals pending.")
    n = _notify(db, "digest", "Daily digest", body, {"digest": d})
    return {"notification_id": n.id, "summary": body}


def study_schedule(db: Session, task: ScheduledTask, now: datetime) -> dict:
    due = [t for t in db.query(StudyTask).filter(StudyTask.deleted_at.is_(None),
                                                 StudyTask.status.notin_(["done", "skipped"])).all()
           if t.due_at and _aware(t.due_at) <= now + timedelta(days=1)]
    revs = [t for t in db.query(StudyTask).filter(StudyTask.deleted_at.is_(None)).all()
            if t.revise_at and _aware(t.revise_at) <= now]
    if not due and not revs:
        return {"due": 0, "revisions": 0}
    body = "; ".join([f"Study: {t.title}" for t in due[:5]] + [f"Revise: {t.title}" for t in revs[:5]])
    _notify(db, "study", "Today's study schedule", body, {"due": [t.id for t in due], "revisions": [t.id for t in revs]})
    return {"due": len(due), "revisions": len(revs)}


def follow_up(db: Session, task: ScheduledTask, now: datetime) -> dict:
    items = [a for a in db.query(Application).filter(Application.deleted_at.is_(None),
                                                     Application.state.notin_(TERMINAL_APP)).all()
             if a.follow_up_at and _aware(a.follow_up_at) <= now]
    for a in items:   # reminders only: never contacts anyone or changes application state
        _notify(db, "follow_up", "Follow-up due", f"Application {a.id} is due for a follow-up.",
                {"application_id": a.id, "job_id": a.job_id})
    return {"reminders": len(items)}


def weekly_report(db: Session, now: datetime) -> dict:
    since = now - timedelta(days=7)
    funnel = Counter(a.state for a in db.query(Application).filter(Application.deleted_at.is_(None)).all())
    ev = db.query(ApplicationEvent).filter(ApplicationEvent.created_at >= since).all()
    return {"period": {"from": since.isoformat(), "to": now.isoformat()},
            "funnel": dict(sorted(funnel.items())),
            "activity": {"jobs_discovered": sum(1 for j in db.query(Job).filter(Job.deleted_at.is_(None)).all()
                                                if _aware(j.first_seen_at) >= since),
                         "application_events": len(ev),
                         "state_changes": sum(1 for e in ev if e.to_state),
                         "study_tasks_completed": db.query(StudyTask).filter(StudyTask.status == "done",
                                                                             StudyTask.updated_at >= since).count(),
                         "interview_sessions": db.query(InterviewSession).filter(
                             InterviewSession.created_at >= since).count()}}


def weekly_report_task(db: Session, task: ScheduledTask, now: datetime) -> dict:
    r = weekly_report(db, now)
    _set(db, "report.weekly.latest", r)
    n = _notify(db, "report", "Weekly report", f"Funnel: {r['funnel']}", {"report": r})
    return {"notification_id": n.id, "funnel": r["funnel"]}


HANDLERS = {"job_scan": job_scan, "daily_digest": daily_digest, "study_schedule": study_schedule,
            "follow_up": follow_up, "weekly_report": weekly_report_task}
assert_no_submit_kind(HANDLERS)
