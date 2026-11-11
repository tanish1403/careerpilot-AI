"""Matching service: score jobs against the current profile, persist and reuse MatchResult rows.

Callable by the scheduler: `score_all(db)`."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..core.untrusted import injection_flags, wrap_untrusted
from ..db.base import utcnow
from ..db.models import Job, JobRequirement, JobSourceRecord, MatchFeedback, MatchResult
from ..job_connectors.normalize import parse_dt
from .config import DISCLAIMER, MatchConfig, load_config
from .eligibility import Req
from .engine import JobCtx, score
from .profile import ProfileSnapshot, load_profile


class NoProfileError(Exception):
    pass


def job_ctx(db: Session, job: Job) -> JobCtx:
    reqs = (db.query(JobRequirement).filter(JobRequirement.job_id == job.id)
            .order_by(JobRequirement.created_at, JobRequirement.id).all())
    recs = db.query(JobSourceRecord).filter(JobSourceRecord.job_id == job.id,
                                            JobSourceRecord.deleted_at.is_(None)).all()
    kinds = sorted({(r.raw or {}).get("_cp", {}).get("kind") or "unknown" for r in recs})
    vt = None
    for r in recs:
        vt = vt or parse_dt((r.raw or {}).get("validThrough"))
    return JobCtx(
        id=job.id, title=job.title, company=job.company_name, location=job.location,
        work_mode=job.work_mode or "unknown", description=job.description or "", seniority=job.seniority,
        salary_text=job.salary_text, posted_at=job.posted_at, first_seen_at=job.first_seen_at,
        status=job.status, version=job.version or 1,
        requirements=sorted([Req(r.id, r.text, r.kind, r.mandatory, r.normalized) for r in reqs],
                            key=lambda x: (x.kind, x.normalized or "", x.text)),
        source_kinds=kinds, valid_through=vt)


def _as_of(as_of: datetime | None) -> datetime:
    d = as_of or utcnow()
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def latest_match(db: Session, job_id: str, profile_id: str | None = None) -> MatchResult | None:
    q = db.query(MatchResult).filter(MatchResult.job_id == job_id, MatchResult.deleted_at.is_(None))
    if profile_id:
        q = q.filter(MatchResult.profile_id == profile_id)
    return q.order_by(MatchResult.created_at.desc(), MatchResult.id.desc()).first()


def score_job(db: Session, job: Job, snap: ProfileSnapshot, cfg: MatchConfig, *, as_of: datetime | None = None,
              force: bool = False) -> tuple[MatchResult, bool]:
    """Returns (match, reused). Same profile_version + profile content + job_version + config_version
    on the same day reuses the stored row, so results are reproducible."""
    as_of = _as_of(as_of)
    jv = job.version or 1
    prev = (db.query(MatchResult).filter(
        MatchResult.job_id == job.id, MatchResult.profile_id == snap.profile_id,
        MatchResult.profile_version == snap.version, MatchResult.job_version == jv,
        MatchResult.config_version == cfg.version, MatchResult.deleted_at.is_(None))
        .order_by(MatchResult.created_at.desc(), MatchResult.id.desc()).all())
    for m in prev:
        meta = (m.evidence or {}).get("meta", {})
        if (meta.get("profile_hash") == snap.hash and not force
                and str(meta.get("as_of", ""))[:10] == as_of.date().isoformat()):
            return m, True
    res = score(job_ctx(db, job), snap, cfg, as_of)
    res["evidence"]["meta"].update({"profile_hash": snap.hash, "config": cfg.to_dict()})
    for m in prev:     # numerically identical on a later day: keep the existing row, refresh nothing
        if (meta := (m.evidence or {}).get("meta", {})).get("profile_hash") == snap.hash and (
                m.fit_score, m.priority_score, m.eligibility, m.factors) == (
                res["fit_score"], res["priority_score"], res["eligibility"], res["factors"]) and not force:
            m.evidence = {**(m.evidence or {}), "meta": {**meta, "as_of": as_of.isoformat()}}
            db.flush()
            return m, True
    m = MatchResult(workspace_id="default", profile_id=snap.profile_id, job_id=job.id,
                    profile_version=snap.version, job_version=jv, config_version=cfg.version, **res)
    db.add(m)
    db.flush()
    return m, False


def score_all(db: Session, job_ids: list[str] | None = None, *, force: bool = False,
              as_of: datetime | None = None) -> dict:
    snap = load_profile(db)
    if snap is None:
        raise NoProfileError("Create a candidate profile before scoring jobs.")
    cfg = load_config(db)
    q = db.query(Job).filter(Job.deleted_at.is_(None))
    q = q.filter(Job.id.in_(job_ids)) if job_ids else q.filter(Job.status == "open")
    scored = reused = failed = 0
    for job in q.order_by(Job.created_at, Job.id).all():
        try:
            with db.begin_nested():
                _, was_reused = score_job(db, job, snap, cfg, as_of=as_of, force=force)
            reused += was_reused
            scored += not was_reused
        except Exception:  # noqa: BLE001  one bad job never stops the batch
            failed += 1
    db.commit()
    return {"scored": scored, "reused": reused, "failed": failed, "profile_version": snap.version,
            "config_version": cfg.version}


def add_feedback(db: Session, match_id: str, *, relevant: bool | None, action: str | None,
                 reason: str | None) -> MatchFeedback:
    if action not in (None, "applied", "skip"):
        raise ValueError("action must be 'applied' or 'skip'")
    if relevant is None and action is None and not reason:
        raise ValueError("provide relevant, action or reason")
    fb = MatchFeedback(workspace_id="default", match_id=match_id, relevant=relevant, action=action,
                       reason=(reason or None) and reason[:2000])
    db.add(fb)
    db.flush()
    return fb


def match_to_dict(m: MatchResult) -> dict:
    ev = m.evidence or {}
    return {"id": m.id, "job_id": m.job_id, "profile_id": m.profile_id, "eligibility": m.eligibility,
            "eligibility_details": m.eligibility_details or [], "fit_score": m.fit_score,
            "priority_score": m.priority_score, "factors": m.factors or {}, "missing": m.missing or [],
            "priority_breakdown": ev.get("priority", {}), "disclaimer": DISCLAIMER,
            "versions": {"profile_version": m.profile_version, "job_version": m.job_version,
                         "config_version": m.config_version, "as_of": (ev.get("meta") or {}).get("as_of")},
            "created_at": m.created_at.isoformat() if m.created_at else None}


def job_prompt_view(job: Job) -> str:
    """Job text for any LLM prompt: always wrapped as untrusted data."""
    return wrap_untrusted(f"{job.title} at {job.company_name}\n\n{job.description}", source=f"job:{job.id}")


def job_injection_flags(job: Job) -> list[str]:
    return injection_flags(f"{job.title}\n{job.description}")
