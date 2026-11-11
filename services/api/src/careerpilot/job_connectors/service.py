"""Ingestion service: persist connector results with dedupe, provenance, freshness and closed detection.

Public entry points for other lanes (scheduler): `run_source(db, source_id)`, `run_all_sources(db)`."""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..core.audit import audit
from ..db.base import utcnow
from ..db.models import (Company, IngestionLog, Job, JobRequirement, JobSource, JobSourceRecord)
from .errors import BlockedError, ConfigError, ConnectorError
from .http import HttpFetcher, get_limiter
from .interface import ConnectorResult, RawJob
from .normalize import (canonical_url, clean_description, cmp_key, extract_salary_text, infer_seniority,
                        infer_work_mode, norm_company, probable_duplicate, url_key)
from .policy import RobotsChecker
from .registry import build_connector
from .requirements import extract_requirements

WS = "default"
MAX_WARNINGS = 50


def run_coro_sync(coro):
    """Run a coroutine from sync code, even when an event loop is already running in this thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def _t():
        try:
            box["v"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=_t)
    th.start()
    th.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


@dataclass
class IngestStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    reopened: int = 0
    closed: int = 0
    skipped_deleted: int = 0
    job_ids: list[str] = field(default_factory=list)


def _aware(dt: datetime | None) -> datetime | None:
    from datetime import timezone
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class _Index:
    """Per-run lookup structures (company -> jobs) for cross-source duplicate detection."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.by_company: dict[str, list[Job]] | None = None

    def _load(self) -> dict[str, list[Job]]:
        if self.by_company is None:
            self.by_company = {}
            for j in self.db.query(Job).filter(Job.workspace_id == WS).all():
                self.by_company.setdefault(norm_company(j.company_name), []).append(j)
        return self.by_company

    def add(self, job: Job) -> None:
        self._load().setdefault(norm_company(job.company_name), []).append(job)

    def find_similar(self, raw: RawJob) -> Job | None:
        cands = [j for j in self._load().get(norm_company(raw.company), []) if j.deleted_at is None]
        ck = cmp_key(raw.company, raw.title, raw.location)
        for j in cands:
            if cmp_key(j.company_name, j.title, j.location) == ck:
                return j
        for j in cands:
            if probable_duplicate(raw.title, raw.location, j.title, j.location):
                return j
        return None


def _get_company(db: Session, name: str) -> Company:
    key = norm_company(name)
    for c in db.query(Company).filter(Company.workspace_id == WS, Company.deleted_at.is_(None)).all():
        if norm_company(c.name) == key:
            return c
    c = Company(workspace_id=WS, name=name[:200])
    db.add(c)
    db.flush()
    return c


def _primary_record(db: Session, job: Job) -> JobSourceRecord | None:
    return (db.query(JobSourceRecord).filter(JobSourceRecord.job_id == job.id,
                                             JobSourceRecord.deleted_at.is_(None))
            .order_by(JobSourceRecord.first_seen_at, JobSourceRecord.created_at).first())


_FIELDS = ("title", "location", "work_mode", "description", "salary_text", "seniority", "posted_at",
           "requirements")


def _apply(job: Job, raw: RawJob, desc: str, primary: bool) -> bool:
    """Apply incoming data; non-primary sources only fill blanks. Returns True when content changed."""
    incoming = {"title": raw.title.strip()[:400], "location": (raw.location or None) and raw.location[:300],
                "work_mode": raw.work_mode or "unknown", "description": desc,
                "salary_text": (raw.salary_text or None) and raw.salary_text[:200],
                "seniority": raw.seniority or infer_seniority(raw.title),
                "posted_at": _aware(raw.posted_at), "requirements": list(raw.requirements or [])}
    changed = False
    for k, v in incoming.items():
        cur = getattr(job, k)
        if k == "posted_at":
            cur = _aware(cur)
        if primary:
            if v in (None, "", [], "unknown") and cur not in (None, "", [], "unknown") and k != "title":
                continue          # never blank out known data because a source omitted it
            if cur != v:
                setattr(job, k, v)
                changed = True
        else:
            if cur in (None, "", [], "unknown") and v not in (None, "", [], "unknown"):
                setattr(job, k, v)
                changed = True
    return changed


def rebuild_requirements(db: Session, job: Job, explicit: list[str] | None = None) -> int:
    db.query(JobRequirement).filter(JobRequirement.job_id == job.id).delete()
    items = extract_requirements(job.description, explicit or job.requirements)
    for it in items:
        db.add(JobRequirement(workspace_id=WS, job_id=job.id, text=it.text[:2000], kind=it.kind,
                              mandatory=it.mandatory, normalized=it.normalized))
    return len(items)


def _cp(raw: RawJob, now: datetime) -> dict:
    return {"kind": raw.source_kind}


def upsert_raw(db: Session, raw: RawJob, source: JobSource | None, idx: _Index, now: datetime,
               stats: IngestStats) -> Job | None:
    desc = clean_description(raw.description)
    if not raw.title or not raw.company:
        return None
    canon = raw.canonical_url or canonical_url(raw.source_url)
    rec_q = db.query(JobSourceRecord).filter(JobSourceRecord.deleted_at.is_(None),
                                             JobSourceRecord.external_id == raw.external_id)
    rec_q = rec_q.filter(JobSourceRecord.source_id == (source.id if source else None)) if source \
        else rec_q.filter(JobSourceRecord.source_id.is_(None), JobSourceRecord.source_url == raw.source_url)
    rec = rec_q.first()
    job: Job | None = db.get(Job, rec.job_id) if rec else None
    if job is None:
        job = (db.query(Job).filter(Job.workspace_id == WS, Job.dedupe_key == url_key(canon)).first()
               if canon else None) or idx.find_similar(raw)
    if job is not None and job.deleted_at is not None:
        stats.skipped_deleted += 1
        return None
    created = job is None
    if created:
        dk = url_key(canon) if canon else cmp_key(raw.company, raw.title, raw.location)
        job = Job(workspace_id=WS, dedupe_key=dk, company_id=_get_company(db, raw.company).id,
                  title=raw.title.strip()[:400], company_name=raw.company.strip()[:200],
                  canonical_url=canon[:1000] or raw.source_url[:1000], first_seen_at=now,
                  last_verified_at=now, status="open", version=1, description="", requirements=[])
        db.add(job)
        db.flush()
        idx.add(job)
        changed = _apply(job, raw, desc, True)
        rebuild_requirements(db, job, raw.requirements)
        stats.created += 1
    else:
        primary_rec = _primary_record(db, job)
        primary = primary_rec is None or (rec is not None and rec.id == primary_rec.id)
        changed = _apply(job, raw, desc, primary)
        was_closed = job.status == "closed"
        if was_closed:
            job.status = "open"
            stats.reopened += 1
            changed = True
        if changed:
            job.version = (job.version or 1) + 1
            rebuild_requirements(db, job, raw.requirements)
            stats.updated += 1
        else:
            stats.unchanged += 1
        job.last_verified_at = now
    rawdata = dict(raw.raw or {})
    rawdata["_cp"] = _cp(raw, now)
    if rec is None:
        db.add(JobSourceRecord(workspace_id=WS, job_id=job.id, source_id=source.id if source else None,
                               external_id=raw.external_id[:200], source_url=raw.source_url[:1000],
                               collection_method=raw.collection_method, first_seen_at=now,
                               last_verified_at=now, raw=rawdata))
    else:
        rec.job_id = job.id
        rec.source_url = raw.source_url[:1000]
        rec.last_verified_at = now
        rec.raw = rawdata            # replaces raw => clears any missing_since marker
    db.flush()
    stats.job_ids.append(job.id)
    return job


def ingest_result(db: Session, source: JobSource | None, result: ConnectorResult,
                  now: datetime | None = None) -> IngestStats:
    now = now or utcnow()
    stats = IngestStats()
    idx = _Index(db)
    seen_rec_ids: set[str] = set()
    for raw in result.jobs:
        try:
            with db.begin_nested():
                job = upsert_raw(db, raw, source, idx, now, stats)
        except Exception as e:  # noqa: BLE001  one bad job never aborts the batch
            result.warnings.append(f"failed to store job '{raw.title[:60]}': {type(e).__name__}")
            result.complete = False
            continue
        if job is not None:
            rec = db.query(JobSourceRecord).filter(
                JobSourceRecord.job_id == job.id, JobSourceRecord.external_id == raw.external_id[:200],
                JobSourceRecord.source_id == (source.id if source else None)).first()
            if rec:
                seen_rec_ids.add(rec.id)
    if result.complete and source is not None:
        stats.closed = _detect_closed(db, source, seen_rec_ids, now)
    return stats


def _detect_closed(db: Session, source: JobSource, seen: set[str], now: datetime) -> int:
    """Only called for complete results. Marks (never deletes); a job closes when every one of its
    source records is missing from a complete listing of its own source."""
    recs = db.query(JobSourceRecord).filter(JobSourceRecord.source_id == source.id,
                                            JobSourceRecord.deleted_at.is_(None)).all()
    touched: set[str] = set()
    for r in recs:
        if r.id in seen:
            continue
        cp = dict((r.raw or {}).get("_cp") or {})
        if not cp.get("missing_since"):
            cp["missing_since"] = now.isoformat()
            r.raw = {**(r.raw or {}), "_cp": cp}
        touched.add(r.job_id)
    closed = 0
    for jid in touched:
        job = db.get(Job, jid)
        if job is None or job.deleted_at is not None or job.status == "closed":
            continue
        all_recs = db.query(JobSourceRecord).filter(JobSourceRecord.job_id == jid,
                                                    JobSourceRecord.deleted_at.is_(None)).all()
        if all(r.source_id is not None and (r.raw or {}).get("_cp", {}).get("missing_since")
               for r in all_recs):
            job.status = "closed"
            job.version = (job.version or 1) + 1
            closed += 1
    db.flush()
    return closed


# ---- running sources --------------------------------------------------------
def _finish_log(db: Session, source: JobSource, log: IngestionLog, *, status: str, error: str | None = None,
                result: ConnectorResult | None = None, stats: IngestStats | None = None) -> IngestionLog:
    log.status = status
    log.error = error[:1000] if error else None
    if result is not None:
        log.fetched = len(result.jobs)
        log.warnings = result.warnings[:MAX_WARNINGS]
    if stats is not None:
        log.created, log.updated, log.closed = stats.created, stats.updated, stats.closed
    source.last_run_at = utcnow()
    source.last_status = status
    source.last_error = log.error
    return log


def run_source(db: Session, source_id: str, *, connector=None) -> IngestionLog:
    """Fetch + ingest one source. Never raises for connector failures: a failed IngestionLog is
    returned so other sources keep running. Commits."""
    source = db.get(JobSource, source_id)
    if source is None or source.deleted_at is not None:
        raise LookupError("source not found")
    log = IngestionLog(workspace_id=WS, source_id=source.id, status="running")
    db.add(log)
    db.commit()           # the log row survives a failed ingest rollback
    log_id = log.id
    if not source.enabled:
        _finish_log(db, source, log, status="skipped", error="source is disabled")
        db.commit()
        return log
    try:
        conn = connector or build_connector(
            source.kind, limiter=get_limiter(f"source:{source.id}", source.rate_limit_per_min))
        result: ConnectorResult = run_coro_sync(conn.fetch(source.config or {}))
        stats = ingest_result(db, source, result)
        status = "success" if (result.complete and not result.warnings) else "partial"
        _finish_log(db, source, log, status=status, result=result, stats=stats)
        audit(db, "jobs.ingest", subject_type="job_source", subject_id=source.id,
              detail={"status": status, "fetched": len(result.jobs), "created": stats.created,
                      "closed": stats.closed})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        source = db.get(JobSource, source_id)
        log = db.get(IngestionLog, log_id)
        msg = str(e) if isinstance(e, ConnectorError) else f"{type(e).__name__}: {e}"
        _finish_log(db, source, log, status="failed", error=msg)
    db.commit()
    return log


def run_all_sources(db: Session) -> list[IngestionLog]:
    logs = []
    ids = [s.id for s in db.query(JobSource).filter(JobSource.deleted_at.is_(None),
                                                   JobSource.enabled.is_(True)).all()]
    for sid in ids:
        try:
            logs.append(run_source(db, sid))
        except Exception:  # noqa: BLE001
            db.rollback()
    return logs


def dry_run_source(db: Session, source_id: str, *, connector=None) -> dict:
    """Fetch without persisting anything."""
    source = db.get(JobSource, source_id)
    if source is None or source.deleted_at is not None:
        raise LookupError("source not found")
    try:
        conn = connector or build_connector(
            source.kind, limiter=get_limiter(f"source:{source.id}", source.rate_limit_per_min))
        res: ConnectorResult = run_coro_sync(conn.fetch(source.config or {}))
        return {"ok": True, "job_count": len(res.jobs), "complete": res.complete,
                "warnings": res.warnings[:MAX_WARNINGS],
                "sample": [{"title": j.title, "company": j.company, "url": j.source_url}
                           for j in res.jobs[:3]]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e) if isinstance(e, ConnectorError) else type(e).__name__}


# ---- manual ingestion -------------------------------------------------------
def import_url(db: Session, url: str) -> tuple[Job, list[str]]:
    from .url_import import fetch_url_posting

    async def go():
        async with HttpFetcher(limiter=get_limiter("user_url", 20)) as http:
            return await fetch_url_posting(http, RobotsChecker(http), url)
    raw, warnings = run_coro_sync(go())
    res = ConnectorResult(jobs=[raw], complete=False, warnings=warnings)
    stats = ingest_result(db, None, res)
    if not stats.job_ids:
        raise ConnectorError("The job was not stored (it may have been deleted earlier).")
    job = db.get(Job, stats.job_ids[0])
    audit(db, "jobs.import_url", subject_type="job", subject_id=job.id, detail={"host": raw.source_url[:80]})
    db.commit()
    return job, warnings


def import_text(db: Session, *, title: str, company: str, description: str, url: str | None = None) -> Job:
    if not title.strip() or not company.strip() or not description.strip():
        raise ConfigError("title, company and description are required")
    h = hashlib.sha1(f"{company}|{title}|{description[:300]}".encode()).hexdigest()[:16]
    src_url = url.strip() if url else f"manual:{h}"
    raw = RawJob(source_kind="manual", external_id=h, source_url=src_url,
                 canonical_url=canonical_url(src_url) if url else src_url, title=title.strip(),
                 company=company.strip(), description=description,
                 work_mode=infer_work_mode(title, description[:1500]),
                 salary_text=extract_salary_text(description), seniority=infer_seniority(title),
                 collection_method="user_text", raw={"manual": True})
    stats = ingest_result(db, None, ConnectorResult(jobs=[raw], complete=False))
    job = db.get(Job, stats.job_ids[0])
    db.commit()
    return job


_CLOSED_MARKERS = re.compile(r"(no longer (accepting|available)|position (has been|is) filled|"
                             r"job (is )?(closed|expired)|this posting has expired|no longer open)", re.I)


def verify_job(db: Session, job_id: str) -> dict:
    """Re-check the primary source link (robots-respecting, no bypass)."""
    job = db.get(Job, job_id)
    if job is None or job.deleted_at is not None:
        raise LookupError("job not found")
    rec = _primary_record(db, job)
    url = rec.source_url if rec else job.canonical_url
    if not url.startswith("http"):
        return {"status": "unverifiable", "note": "job has no web link (manually entered)",
                "checked_url": None}

    async def go():
        from .errors import ConnectorHTTPError
        from .policy import check_url_policy
        check_url_policy(url)
        async with HttpFetcher(limiter=get_limiter("verify", 30), max_retries=1) as http:
            if not await RobotsChecker(http).allowed(url):
                return "unverifiable", "robots.txt disallows automated checks; open the link yourself", None
            try:
                resp = await http.get(url)
            except BlockedError as e:
                return "unverifiable", str(e), None
            except ConnectorHTTPError as e:
                if e.status in (404, 410):
                    return "closed", f"HTTP {e.status}", e.status
                return "unverifiable", str(e), e.status
            if "error=true" in str(resp.url) or _CLOSED_MARKERS.search(resp.text[:50000]):
                return "closed", "page indicates the posting is no longer open", resp.status_code
            return "open", "link reachable", resp.status_code
    try:
        status, note, code = run_coro_sync(go())
    except BlockedError as e:
        status, note, code = "unverifiable", str(e), None
    now = utcnow()
    if status == "closed" and job.status != "closed":
        job.status = "closed"
        job.version = (job.version or 1) + 1
    elif status == "open":
        job.last_verified_at = now
        if rec:
            rec.last_verified_at = now
        if job.status == "closed":
            job.status = "open"
            job.version = (job.version or 1) + 1
    db.commit()
    return {"status": status, "note": note, "http_status": code, "checked_url": url,
            "verified_at": now.isoformat() if status != "unverifiable" else None, "job_status": job.status}
