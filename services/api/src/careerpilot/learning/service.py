"""Learning: tracks, study plans, skill gaps, resources, progress, SM-2 revision, export, replan.

Per-task extras (hours, SM-2 state) live in Setting rows `study_task_meta:<task_id>` because
StudyTask has no JSON column (avoids a migration)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import Application, Job, JobRequirement, LearningResource, Setting, StudyPlan, StudyTask
from ..matching.profile import load_profile
from ..matching.taxonomy import canonical_skill

DATA = Path(__file__).parent / "data"
SEED_RESOURCES = [  # official documentation roots only; never marked as accessed/verified by us
    ("Python documentation", "https://docs.python.org/3/", "python"),
    ("MDN Web Docs", "https://developer.mozilla.org/", "javascript"),
    ("React documentation", "https://react.dev/", "react"),
    ("PostgreSQL documentation", "https://www.postgresql.org/docs/", "sql"),
    ("scikit-learn user guide", "https://scikit-learn.org/stable/user_guide.html", "machine learning"),
    ("FastAPI documentation", "https://fastapi.tiangolo.com/", "api"),
]
TERMINAL_TASK = ("done", "skipped")


# ---- templates ---------------------------------------------------------------
@lru_cache
def templates() -> dict[str, dict]:
    out = {}
    for p in sorted(DATA.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out[t["key"]] = t
    return out


# ---- SM-2 --------------------------------------------------------------------
def sm2_next(ease: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """Classic SM-2. quality 0-5. Returns (ease, interval_days, repetitions)."""
    if not 0 <= quality <= 5:
        raise ValueError("quality must be 0-5")
    if quality < 3:
        reps, interval = 0, 1
    else:
        reps += 1
        interval = 1 if reps == 1 else 6 if reps == 2 else max(1, round(interval * ease))
    ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return round(ease, 4), interval, reps


def _meta_key(task_id: str) -> str:
    return f"study_task_meta:{task_id}"


def get_meta(db: Session, task_id: str) -> dict:
    row = db.get(Setting, _meta_key(task_id))
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def set_meta(db: Session, task_id: str, meta: dict) -> None:
    row = db.get(Setting, _meta_key(task_id))
    if row is None:
        db.add(Setting(key=_meta_key(task_id), value=meta))
    else:
        row.value = meta
    db.flush()


def record_review(db: Session, task: StudyTask, quality: int, now: datetime | None = None) -> dict:
    now = now or utcnow()
    m = get_meta(db, task.id)
    ease, interval, reps = sm2_next(m.get("ease", 2.5), m.get("interval", 0), m.get("reps", 0), quality)
    m.update(ease=ease, interval=interval, reps=reps, last_quality=quality,
             lapses=m.get("lapses", 0) + (1 if quality < 3 else 0), last_review=now.isoformat())
    set_meta(db, task.id, m)
    task.revise_at = now + timedelta(days=interval)
    db.flush()
    return m


def due_revisions(db: Session, now: datetime | None = None) -> list[StudyTask]:
    now = now or utcnow()
    return (db.query(StudyTask).filter(StudyTask.deleted_at.is_(None), StudyTask.revise_at.isnot(None),
                                       StudyTask.revise_at <= now).order_by(StudyTask.revise_at).all())


# ---- skill gaps --------------------------------------------------------------
def candidate_jobs(db: Session, job_ids: list[str] | None = None) -> list[Job]:
    q = db.query(Job).filter(Job.deleted_at.is_(None))
    if job_ids:
        return q.filter(Job.id.in_(job_ids)).all()
    short = {a.job_id for a in db.query(Application).filter(
        Application.deleted_at.is_(None), Application.state.in_(["Shortlisted", "ResumePrepared"])).all()}
    return [j for j in q.all() if j.saved or j.id in short]


def skill_gaps(db: Session, job_ids: list[str] | None = None) -> list[dict]:
    snap = load_profile(db)
    have = set(snap.confirmed_skill_names) if snap else set()   # CONFIRMED skills only
    gaps: dict[str, dict] = {}
    for job in candidate_jobs(db, job_ids):
        reqs = db.query(JobRequirement).filter(JobRequirement.job_id == job.id, JobRequirement.deleted_at.is_(None),
                                               JobRequirement.kind == "skill").all()
        items = [(r.normalized or r.text, r.mandatory) for r in reqs]
        if not items:
            items = [(str(x), False) for x in (job.requirements or []) if isinstance(x, str)]
        seen = set()
        for text, mandatory in items:
            skill = canonical_skill(text.strip())
            if not skill or skill in have or skill in seen:
                continue
            seen.add(skill)
            g = gaps.setdefault(skill, {"skill": skill, "jobs": [], "count": 0, "mandatory_count": 0})
            g["jobs"].append({"id": job.id, "title": job.title})
            g["count"] += 1
            g["mandatory_count"] += 1 if mandatory else 0
    return sorted(gaps.values(), key=lambda g: (-g["count"], -g["mandatory_count"], g["skill"]))


# ---- plans -------------------------------------------------------------------
def _schedule(tasks: list[tuple[StudyTask, float]], start: datetime, hours_per_week: float) -> None:
    per_day = max(hours_per_week, 0.5) / 7.0
    cum = 0.0
    for t, h in tasks:
        cum += max(h, 0.5)
        t.due_at = start + timedelta(days=cum / per_day)


def generate_plan(db: Session, tracks: list[str], hours_per_week: float = 6.0,
                  job_ids: list[str] | None = None, name: str | None = None,
                  now: datetime | None = None) -> StudyPlan:
    now = now or utcnow()
    unknown = [t for t in tracks if t not in templates()]
    if unknown:
        raise ValueError(f"unknown track(s): {', '.join(unknown)}")
    gaps = skill_gaps(db, job_ids)[:8]
    if not tracks and not gaps:
        raise ValueError("choose at least one track (no skill gaps found to base a plan on)")
    plan = StudyPlan(name=name or "Study plan: " + (", ".join(templates()[t]["name"] for t in tracks) or "skill gaps"),
                     track=",".join(tracks) or None, hours_per_week=hours_per_week,
                     motivation={"tracks": tracks, "skill_gaps": [{"skill": g["skill"], "jobs": g["jobs"]} for g in gaps],
                                 "job_ids": sorted({j["id"] for g in gaps for j in g["jobs"]}),
                                 "generated_at": now.isoformat()})
    db.add(plan)
    db.flush()
    work: list[tuple[StudyTask, float]] = []

    def add(title: str, topic: str, hours: float, reason: str) -> None:
        t = StudyTask(plan_id=plan.id, title=title, topic=topic, reason=reason)
        db.add(t)
        db.flush()
        set_meta(db, t.id, {"hours": hours})
        work.append((t, hours))

    for g in gaps:  # gap tasks first: they are what saved jobs asked for
        titles = ", ".join(j["title"] for j in g["jobs"][:3])
        add(f"Learn {g['skill']} fundamentals and build a small exercise", g["skill"], 4.0,
            f"Skill gap: required by {g['count']} saved job(s) ({titles}) and not a confirmed profile skill.")
    for key in tracks:
        tpl = templates()[key]
        for tp in tpl["topics"]:
            add(tp["title"], tp["topic"], float(tp["hours"]), f"Part of the {tpl['name']} track.")
    _schedule(work, now, hours_per_week)
    db.flush()
    return plan


def replan(db: Session, plan: StudyPlan, hours_per_week: float | None = None,
           now: datetime | None = None) -> dict:
    """Reschedule unfinished tasks from now (overdue work shifts forward); lapsed reviews first."""
    now = now or utcnow()
    if hours_per_week:
        plan.hours_per_week = hours_per_week
    tasks = (db.query(StudyTask).filter(StudyTask.plan_id == plan.id, StudyTask.deleted_at.is_(None),
                                        StudyTask.status.notin_(TERMINAL_TASK)).all())
    metas = {t.id: get_meta(db, t.id) for t in tasks}
    tasks.sort(key=lambda t: (-metas[t.id].get("lapses", 0), t.due_at or now + timedelta(days=3650), t.created_at))
    overdue = sum(1 for t in tasks if t.due_at and t.due_at.replace(tzinfo=t.due_at.tzinfo or now.tzinfo) < now)
    _schedule([(t, metas[t.id].get("hours", 1.0)) for t in tasks], now, plan.hours_per_week or 6.0)
    db.flush()
    return {"rescheduled": len(tasks), "overdue_before": overdue, "hours_per_week": plan.hours_per_week}


def task_dict(db: Session, t: StudyTask) -> dict:
    m = get_meta(db, t.id)
    return {"id": t.id, "plan_id": t.plan_id, "title": t.title, "topic": t.topic, "status": t.status,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "revise_at": t.revise_at.isoformat() if t.revise_at else None,
            "resource_id": t.resource_id, "reason": t.reason, "hours": m.get("hours"),
            "sm2": {k: m[k] for k in ("ease", "interval", "reps", "last_quality") if k in m}}


def plan_dict(db: Session, p: StudyPlan, with_tasks: bool = False) -> dict:
    tasks = db.query(StudyTask).filter(StudyTask.plan_id == p.id, StudyTask.deleted_at.is_(None)
                                       ).order_by(StudyTask.due_at, StudyTask.created_at).all()
    d = {"id": p.id, "name": p.name, "track": p.track, "motivation": p.motivation or {},
         "hours_per_week": p.hours_per_week, "task_count": len(tasks),
         "done_count": sum(1 for t in tasks if t.status == "done")}
    if with_tasks:
        d["tasks"] = [task_dict(db, t) for t in tasks]
    return d


def export_markdown(db: Session, p: StudyPlan) -> str:
    d = plan_dict(db, p, True)
    lines = [f"# {d['name']}", "", f"- Hours per week: {d['hours_per_week']}",
             f"- Progress: {d['done_count']}/{d['task_count']} tasks done"]
    mot = d["motivation"]
    if mot.get("skill_gaps"):
        lines += ["", "## Why this plan (skill gaps from saved jobs)"]
        for g in mot["skill_gaps"]:
            lines.append(f"- **{g['skill']}**: " + ", ".join(j["title"] for j in g["jobs"]))
    lines += ["", "## Tasks"]
    for t in d["tasks"]:
        box = "x" if t["status"] == "done" else " "
        due = f" (due {t['due_at'][:10]})" if t["due_at"] else ""
        rev = f" [revise {t['revise_at'][:10]}]" if t["revise_at"] else ""
        lines.append(f"- [{box}] {t['title']}{due}{rev}")
        if t["reason"]:
            lines.append(f"  - Reason: {t['reason']}")
    return "\n".join(lines) + "\n"


# ---- resources / progress ----------------------------------------------------
def resources(db: Session) -> list[dict]:
    rows = [{"id": r.id, "title": r.title, "url": r.url, "topic": r.topic, "accessed_on": r.accessed_on,
             "origin": "user"} for r in db.query(LearningResource).filter(
                 LearningResource.deleted_at.is_(None)).order_by(LearningResource.created_at).all()]
    have = {r["url"] for r in rows}
    seeds = [{"id": None, "title": t, "url": u, "topic": tp, "accessed_on": None, "origin": "seed"}
             for t, u, tp in SEED_RESOURCES if u not in have]
    return rows + seeds


def progress(db: Session, now: datetime | None = None) -> dict:
    topics: dict[str, dict] = {}
    for t in db.query(StudyTask).filter(StudyTask.deleted_at.is_(None)).all():
        k = t.topic or "general"
        e = topics.setdefault(k, {"topic": k, "total": 0, "done": 0})
        e["total"] += 1
        e["done"] += 1 if t.status == "done" else 0
    for e in topics.values():
        e["percent"] = round(100 * e["done"] / e["total"], 1) if e["total"] else 0.0
    dsa_topics = {tp["topic"] for tp in templates()["dsa"]["topics"]}
    tot = sum(e["total"] for e in topics.values())
    done = sum(e["done"] for e in topics.values())
    return {"topics": sorted(topics.values(), key=lambda e: e["topic"]),
            "dsa": [e for e in topics.values() if e["topic"] in dsa_topics],
            "overall": {"total": tot, "done": done, "percent": round(100 * done / tot, 1) if tot else 0.0},
            "due_revisions": len(due_revisions(db, now))}
