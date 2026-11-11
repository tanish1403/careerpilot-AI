"""Lane C: jobs list/detail/import/verify."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.base import utcnow
from ...db.models import Job, JobRequirement, JobSource, JobSourceRecord, MatchResult
from ...db.session import get_db
from ...job_connectors import service
from ...job_connectors.errors import BlockedError, ConnectorError
from ...job_connectors.normalize import parse_salary_range
from ...matching.profile import load_profile
from ...matching.service import job_injection_flags, match_to_dict
from ._lanec import iso

router = APIRouter(tags=["jobs"], dependencies=[Depends(current_user)])
NEW_DAYS = 3


class ImportUrl(BaseModel):
    url: str = Field(min_length=4, max_length=2000)


class ImportText(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    company: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    url: str | None = None


def _records(db: Session, job_ids: list[str]) -> dict[str, list[dict]]:
    if not job_ids:
        return {}
    kinds = {s.id: s.kind for s in db.query(JobSource).all()}
    out: dict[str, list[dict]] = {}
    recs = (db.query(JobSourceRecord).filter(JobSourceRecord.job_id.in_(job_ids), JobSourceRecord.deleted_at.is_(None))
            .order_by(JobSourceRecord.first_seen_at, JobSourceRecord.created_at).all())
    for r in recs:
        cp = (r.raw or {}).get("_cp", {})
        out.setdefault(r.job_id, []).append({
            "id": r.id, "source_id": r.source_id, "kind": kinds.get(r.source_id) or cp.get("kind") or "unknown",
            "url": r.source_url, "external_id": r.external_id, "collection_method": r.collection_method,
            "first_seen_at": iso(r.first_seen_at), "last_verified_at": iso(r.last_verified_at),
            "missing_since": cp.get("missing_since")})
    return out


def _matches(db: Session, job_ids: list[str], profile_id: str | None) -> dict[str, MatchResult]:
    if not job_ids or not profile_id:
        return {}
    out: dict[str, MatchResult] = {}
    for m in (db.query(MatchResult).filter(MatchResult.job_id.in_(job_ids), MatchResult.profile_id == profile_id,
                                           MatchResult.deleted_at.is_(None))
              .order_by(MatchResult.created_at, MatchResult.id).all()):
        out[m.job_id] = m
    return out


def _item(j: Job, recs: list[dict], m: MatchResult | None) -> dict:
    return {"id": j.id, "title": j.title, "company_name": j.company_name, "location": j.location,
            "work_mode": j.work_mode, "seniority": j.seniority, "salary_text": j.salary_text,
            "posted_at": iso(j.posted_at), "first_seen_at": iso(j.first_seen_at),
            "last_verified_at": iso(j.last_verified_at), "status": j.status, "saved": j.saved,
            "sources": [{"kind": r["kind"], "url": r["url"]} for r in recs],
            "match": ({"eligibility": m.eligibility, "fit_score": m.fit_score, "priority_score": m.priority_score,
                       "id": m.id} if m else None)}


@router.get("/jobs")
def list_jobs(q: str | None = None, status: str = "open", source_kind: str | None = None,
              work_mode: str | None = None, location: str | None = None, seniority: str | None = None,
              role: str | None = None, posted_within_days: int | None = Query(default=None, ge=0),
              new_only: bool = False, saved: bool | None = None, min_fit: float | None = None,
              min_salary: float | None = None, sort: str = "priority", limit: int = Query(50, ge=1, le=500),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if sort not in ("priority", "posted", "fit"):
        raise HTTPException(422, "sort must be priority|posted|fit")
    now = utcnow()
    qs = db.query(Job).filter(Job.deleted_at.is_(None))
    if status != "any":
        qs = qs.filter(Job.status == status)
    if q:
        like = f"%{q}%"
        qs = qs.filter(or_(Job.title.ilike(like), Job.company_name.ilike(like), Job.description.ilike(like)))
    if role:
        qs = qs.filter(Job.title.ilike(f"%{role}%"))
    if work_mode:
        qs = qs.filter(Job.work_mode.in_([w.strip() for w in work_mode.split(",")]))
    if location:
        qs = qs.filter(Job.location.ilike(f"%{location}%"))
    if seniority:
        qs = qs.filter(Job.seniority.in_([s.strip() for s in seniority.split(",")]))
    if saved is not None:
        qs = qs.filter(Job.saved.is_(saved))
    if new_only:
        qs = qs.filter(Job.first_seen_at >= now - timedelta(days=NEW_DAYS))
    jobs = qs.all()
    if posted_within_days is not None:
        cutoff = now - timedelta(days=posted_within_days)
        jobs = [j for j in jobs if (j.posted_at or j.first_seen_at).replace(tzinfo=cutoff.tzinfo) >= cutoff]
    if min_salary is not None:
        def ok(j: Job) -> bool:
            r = parse_salary_range(j.salary_text)
            return bool(r and r[1] >= min_salary)
        jobs = [j for j in jobs if ok(j)]
    ids = [j.id for j in jobs]
    recs = _records(db, ids)
    if source_kind:
        wanted = {k.strip() for k in source_kind.split(",")}
        jobs = [j for j in jobs if any(r["kind"] in wanted for r in recs.get(j.id, []))]
    prof = load_profile(db)
    ms = _matches(db, [j.id for j in jobs], prof.profile_id if prof else None)
    if min_fit is not None:
        jobs = [j for j in jobs if j.id in ms and ms[j.id].fit_score >= min_fit]

    def posted(j: Job):
        return (j.posted_at or j.first_seen_at).timestamp() if (j.posted_at or j.first_seen_at) else 0
    if sort == "posted":
        jobs.sort(key=lambda j: (-posted(j), j.id))
    else:
        attr = "priority_score" if sort == "priority" else "fit_score"
        jobs.sort(key=lambda j: (j.id not in ms, -(getattr(ms[j.id], attr) if j.id in ms else 0), -posted(j), j.id))
    total = len(jobs)
    page = jobs[offset:offset + limit]
    return {"items": [_item(j, recs.get(j.id, []), ms.get(j.id)) for j in page], "total": total}


def _get(db: Session, job_id: str) -> Job:
    j = db.get(Job, job_id)
    if j is None or j.deleted_at is not None:
        raise HTTPException(404, "Job not found")
    return j


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    recs = _records(db, [j.id]).get(j.id, [])
    prof = load_profile(db)
    m = _matches(db, [j.id], prof.profile_id if prof else None).get(j.id)
    reqs = (db.query(JobRequirement).filter(JobRequirement.job_id == j.id)
            .order_by(JobRequirement.mandatory.desc(), JobRequirement.created_at, JobRequirement.id).all())
    d = _item(j, recs, None)
    d.update({"description": j.description, "canonical_url": j.canonical_url, "version": j.version,
              "company_id": j.company_id,
              "requirements": [{"id": r.id, "text": r.text, "kind": r.kind, "mandatory": r.mandatory,
                                "normalized": r.normalized} for r in reqs],
              "source_records": recs, "match": match_to_dict(m) if m else None,
              "injection_flags": job_injection_flags(j)})
    return d


def _refused(e: BlockedError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(e), "code": e.code, "apply_url": e.url})


@router.post("/jobs/import-url", status_code=201)
def import_url(body: ImportUrl, db: Session = Depends(get_db)):
    try:
        job, warnings = service.import_url(db, body.url.strip())
    except BlockedError as e:
        return _refused(e)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    return {**_item(job, _records(db, [job.id]).get(job.id, []), None), "warnings": warnings}


@router.post("/jobs/import-text", status_code=201)
def import_text(body: ImportText, db: Session = Depends(get_db)):
    try:
        job = service.import_text(db, title=body.title, company=body.company, description=body.description,
                                  url=body.url)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    return _item(job, _records(db, [job.id]).get(job.id, []), None)


@router.post("/jobs/{job_id}/save")
def save_job(job_id: str, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    j.saved = True
    return {"id": j.id, "saved": True}


@router.post("/jobs/{job_id}/unsave")
def unsave_job(job_id: str, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    j.saved = False
    return {"id": j.id, "saved": False}


@router.post("/jobs/{job_id}/verify")
def verify_job(job_id: str, db: Session = Depends(get_db)):
    _get(db, job_id)
    return service.verify_job(db, job_id)
