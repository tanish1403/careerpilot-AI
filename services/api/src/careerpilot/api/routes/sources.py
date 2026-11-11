"""Lane C: job sources, connector kinds, ingestion logs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user
from ...db.base import utcnow
from ...db.models import IngestionLog, Job, JobSource, JobSourceRecord
from ...db.session import get_db
from ...job_connectors import service
from ...job_connectors.errors import ConnectorError
from ...job_connectors.registry import CONNECTORS, build_connector, kinds_info
from ._lanec import iso, launch_run

router = APIRouter(tags=["sources"], dependencies=[Depends(current_user)])


class SourceIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    rate_limit_per_min: int = Field(default=30, ge=1, le=600)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=600)


def _dto(s: JobSource) -> dict:
    return {"id": s.id, "kind": s.kind, "name": s.name, "config": s.config or {}, "enabled": s.enabled,
            "rate_limit_per_min": s.rate_limit_per_min, "last_run_at": iso(s.last_run_at),
            "last_status": s.last_status, "last_error": s.last_error, "created_at": iso(s.created_at),
            "permitted_usage": CONNECTORS[s.kind].permitted_usage if s.kind in CONNECTORS else None}


def _get(db: Session, sid: str) -> JobSource:
    s = db.get(JobSource, sid)
    if s is None or s.deleted_at is not None:
        raise HTTPException(404, "Source not found")
    return s


def _validate(kind: str, config: dict) -> dict:
    if kind not in CONNECTORS:
        raise HTTPException(422, f"Unknown source kind '{kind}'. Known: {', '.join(sorted(CONNECTORS))}")
    try:
        return build_connector(kind).validate_config(config)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e


def _log_dto(l: IngestionLog) -> dict:
    return {"id": l.id, "source_id": l.source_id, "status": l.status, "fetched": l.fetched, "created": l.created,
            "updated": l.updated, "closed": l.closed, "warnings": l.warnings or [], "error": l.error,
            "created_at": iso(l.created_at)}


@router.get("/sources/kinds")
def kinds() -> list[dict]:
    return kinds_info()


@router.get("/sources")
def list_sources(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(JobSource).filter(JobSource.deleted_at.is_(None)).order_by(JobSource.created_at)
    return {"items": [_dto(s) for s in q.offset(offset).limit(limit).all()], "total": q.count()}


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db)):
    cfg = _validate(body.kind, body.config)
    s = JobSource(workspace_id="default", kind=body.kind, name=body.name, config=cfg, enabled=body.enabled,
                  rate_limit_per_min=body.rate_limit_per_min)
    db.add(s)
    db.flush()
    audit(db, "source.create", subject_type="job_source", subject_id=s.id, detail={"kind": s.kind})
    return _dto(s)


@router.get("/sources/{source_id}")
def get_source(source_id: str, db: Session = Depends(get_db)):
    return _dto(_get(db, source_id))


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch, db: Session = Depends(get_db)):
    s = _get(db, source_id)
    if body.config is not None:
        s.config = _validate(s.kind, body.config)
    for k in ("name", "enabled", "rate_limit_per_min"):
        v = getattr(body, k)
        if v is not None:
            setattr(s, k, v)
    audit(db, "source.update", subject_type="job_source", subject_id=s.id)
    return _dto(s)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, db: Session = Depends(get_db)):
    s = _get(db, source_id)
    s.deleted_at = utcnow()          # soft delete: jobs and provenance are kept
    s.enabled = False
    audit(db, "source.delete", subject_type="job_source", subject_id=s.id)


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, db: Session = Depends(get_db)):
    _get(db, source_id)
    return service.dry_run_source(db, source_id)


@router.post("/sources/{source_id}/run", status_code=202)
def run_source(source_id: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    _get(db, source_id)

    def work(s: Session) -> dict:
        log = service.run_source(s, source_id)
        if log.status == "failed":
            raise ConnectorError(log.error or "source run failed")
        return {"ingestion_log_id": log.id, "status": log.status, "fetched": log.fetched,
                "created": log.created, "updated": log.updated, "closed": log.closed}
    return launch_run(db, bg, "job_connector", {"source_id": source_id}, work)


@router.get("/sources/{source_id}/health")
def source_health(source_id: str, db: Session = Depends(get_db)):
    s = _get(db, source_id)
    logs = (db.query(IngestionLog).filter(IngestionLog.source_id == s.id)
            .order_by(IngestionLog.created_at.desc(), IngestionLog.id).limit(20).all())
    consecutive = 0
    for l in logs:
        if l.status == "failed":
            consecutive += 1
        elif l.status != "skipped":
            break
    done = [l for l in logs if l.status in ("success", "partial", "failed")]
    ok = [l for l in done if l.status != "failed"]
    job_ids = {r.job_id for r in db.query(JobSourceRecord).filter(JobSourceRecord.source_id == s.id,
                                                                   JobSourceRecord.deleted_at.is_(None)).all()}
    jobs = db.query(Job).filter(Job.id.in_(job_ids), Job.deleted_at.is_(None)).all() if job_ids else []
    status = ("disabled" if not s.enabled else "never_run" if not done else
              "failing" if consecutive >= 3 else "degraded" if consecutive >= 1 or done[0].status == "partial"
              else "healthy")
    return {"source_id": s.id, "status": status, "enabled": s.enabled, "last_run_at": iso(s.last_run_at),
            "last_status": s.last_status, "last_error": s.last_error, "consecutive_failures": consecutive,
            "success_rate": round(len(ok) / len(done), 2) if done else None,
            "last_success_at": iso(ok[0].created_at) if ok else None,
            "open_jobs": sum(j.status == "open" for j in jobs), "closed_jobs": sum(j.status == "closed" for j in jobs),
            "recent_logs": [_log_dto(l) for l in logs[:10]]}


@router.get("/ingestion-logs")
def ingestion_logs(source_id: str | None = None, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(IngestionLog).filter(IngestionLog.deleted_at.is_(None))
    if source_id:
        q = q.filter(IngestionLog.source_id == source_id)
    q = q.order_by(IngestionLog.created_at.desc(), IngestionLog.id)
    return {"items": [_log_dto(l) for l in q.offset(offset).limit(limit).all()], "total": q.count()}
