"""Lane C: matching, feedback, configuration."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user
from ...db.models import Job, JobSourceRecord, MatchFeedback, MatchResult
from ...db.session import get_db
from ...matching import service as msvc
from ...matching.config import DEFAULT_PRIORITY_WEIGHTS, DEFAULT_WEIGHTS, load_config, save_config
from ...matching.profile import as_list, load_profile
from ._lanec import iso, launch_run

router = APIRouter(tags=["matching"], dependencies=[Depends(current_user)])


class ScoreIn(BaseModel):
    job_ids: list[str] | None = None
    all: bool = False
    force: bool = False


class FeedbackIn(BaseModel):
    relevant: bool | None = None
    action: str | None = None
    reason: str | None = None


class ConfigIn(BaseModel):
    weights: dict[str, Any]
    priority_weights: dict[str, Any] | None = None


@router.post("/matches/score", status_code=202)
def score(body: ScoreIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if not body.all and not body.job_ids:
        raise HTTPException(422, "Provide job_ids or all=true")
    if load_profile(db) is None:
        raise HTTPException(409, "Create a candidate profile before scoring jobs.")
    ids = None if body.all else list(body.job_ids or [])
    return launch_run(db, bg, "matcher", {"job_ids": ids, "all": body.all, "force": body.force},
                      lambda s: msvc.score_all(s, ids, force=body.force))


@router.get("/matches")
def list_matches(job_id: str | None = None, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(MatchResult).filter(MatchResult.deleted_at.is_(None))
    if job_id:
        q = q.filter(MatchResult.job_id == job_id)
    q = q.order_by(MatchResult.created_at.desc(), MatchResult.id)
    return {"items": [msvc.match_to_dict(m) for m in q.offset(offset).limit(limit).all()], "total": q.count()}


def _match(db: Session, mid: str) -> MatchResult:
    m = db.get(MatchResult, mid)
    if m is None or m.deleted_at is not None:
        raise HTTPException(404, "Match not found")
    return m


@router.get("/matches/{match_id}")
def get_match(match_id: str, db: Session = Depends(get_db)):
    m = _match(db, match_id)
    d = msvc.match_to_dict(m)
    d["feedback"] = [{"id": f.id, "relevant": f.relevant, "action": f.action, "reason": f.reason,
                      "created_at": iso(f.created_at)}
                     for f in db.query(MatchFeedback).filter(MatchFeedback.match_id == m.id)
                     .order_by(MatchFeedback.created_at).all()]
    return d


@router.post("/matches/{match_id}/feedback", status_code=201)
def feedback(match_id: str, body: FeedbackIn, db: Session = Depends(get_db)):
    m = _match(db, match_id)
    try:
        fb = msvc.add_feedback(db, m.id, relevant=body.relevant, action=body.action, reason=body.reason)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit(db, "match.feedback", subject_type="match", subject_id=m.id, detail={"action": fb.action})
    return {"id": fb.id, "match_id": m.id, "relevant": fb.relevant, "action": fb.action, "reason": fb.reason}


@router.get("/matching/config")
def get_config(db: Session = Depends(get_db)):
    return load_config(db).to_dict()


@router.put("/matching/config")
def put_config(body: ConfigIn, db: Session = Depends(get_db)):
    try:
        cfg = save_config(db, body.weights, body.priority_weights)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    audit(db, "matching.config.update", detail={"version": cfg.version})
    return cfg.to_dict()


@router.get("/matching/preferences-filters")
def preferences_filters(db: Session = Depends(get_db)):
    prof = load_profile(db)
    p = prof.preferences if prof else {}
    jobs = db.query(Job).filter(Job.deleted_at.is_(None), Job.status == "open").all()
    count = lambda vals: {k: vals.count(k) for k in sorted(set(v for v in vals if v))}  # noqa: E731
    kinds = [(r.raw or {}).get("_cp", {}).get("kind") for r in
             db.query(JobSourceRecord).filter(JobSourceRecord.deleted_at.is_(None)).all()]
    suggested: dict[str, Any] = {}
    modes = as_list(p.get("work_modes") or p.get("work_mode"))
    if modes:
        suggested["work_mode"] = ",".join(modes)
    if as_list(p.get("seniority")):
        suggested["seniority"] = ",".join(as_list(p.get("seniority")))
    if as_list(p.get("locations")):
        suggested["location"] = as_list(p.get("locations"))[0]
    if p.get("salary_min") or p.get("min_salary"):
        suggested["min_salary"] = p.get("salary_min") or p.get("min_salary")
    return {"has_profile": prof is not None, "suggested": suggested,
            "preferences": {"roles": as_list(p.get("roles")), "locations": as_list(p.get("locations")),
                            "work_modes": modes, "seniority": as_list(p.get("seniority")),
                            "goals": as_list(p.get("goals"))},
            "facets": {"work_mode": count([j.work_mode for j in jobs]), "seniority": count([j.seniority for j in jobs]),
                       "source_kind": count(kinds)},
            "defaults": {"weights": DEFAULT_WEIGHTS, "priority_weights": DEFAULT_PRIORITY_WEIGHTS}}
