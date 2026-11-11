"""Run tracking helpers (WorkflowRun rows) for any lane.

    run = start_run(db, "matcher", {"job_ids": [...]}, idempotency_key="score:abc")
    ...
    finish_run(db, run, output_refs={"count": 3}, usage={"tokens": 10})
    # or fail_run(db, run, "boom")

`start_run` with an idempotency key re-uses an existing live/successful run for the same
(agent, key) instead of creating a duplicate; failed/cancelled runs may be retried.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.base import utcnow
from ...db.models import WorkflowRun
from ..enums import RunStatus
from ..redaction import redact, redact_text

_REUSABLE = (RunStatus.PENDING.value, RunStatus.RUNNING.value, RunStatus.PAUSED.value,
             RunStatus.SUCCEEDED.value)


def find_run_by_key(db: Session, agent: str | None, key: str) -> WorkflowRun | None:
    stmt = (select(WorkflowRun)
            .where(WorkflowRun.idempotency_key == key, WorkflowRun.agent == agent,
                   WorkflowRun.deleted_at.is_(None), WorkflowRun.status.in_(_REUSABLE))
            .order_by(WorkflowRun.created_at.desc()))
    return db.execute(stmt).scalars().first()


def start_run(db: Session, agent: str | None, inputs: dict[str, Any] | None = None,
              idempotency_key: str | None = None, *, status: str = RunStatus.RUNNING.value,
              parent_run_id: str | None = None, workflow_id: str | None = None,
              agent_version: str | None = None) -> WorkflowRun:
    """Create (or, for a repeated idempotency key, return the existing) run."""
    if idempotency_key:
        existing = find_run_by_key(db, agent, idempotency_key)
        if existing is not None:
            return existing
    run = WorkflowRun(agent=agent, agent_version=agent_version, status=status,
                      inputs=redact(inputs or {}), idempotency_key=idempotency_key,
                      parent_run_id=parent_run_id, workflow_id=workflow_id,
                      started_at=utcnow() if status != RunStatus.PENDING.value else None)
    db.add(run)
    db.flush()
    return run


def mark_running(db: Session, run: WorkflowRun) -> WorkflowRun:
    run.status = RunStatus.RUNNING.value
    run.started_at = run.started_at or utcnow()
    db.flush()
    return run


def finish_run(db: Session, run: WorkflowRun, output_refs: dict[str, Any] | None = None,
               usage: dict[str, Any] | None = None, provider_meta: dict[str, Any] | None = None,
               status: str = RunStatus.SUCCEEDED.value) -> WorkflowRun:
    run.status = status
    if output_refs is not None:
        run.output_refs = output_refs
    if usage is not None:
        run.usage = usage
    if provider_meta is not None:
        run.provider_meta = redact(provider_meta)
    run.finished_at = utcnow()
    db.flush()
    return run


def fail_run(db: Session, run: WorkflowRun, error: str | BaseException) -> WorkflowRun:
    msg = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    run.status = RunStatus.FAILED.value
    run.error = redact_text(msg)
    run.finished_at = utcnow()
    db.flush()
    return run


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "+00:00"
    return dt.isoformat()


def run_to_dict(run: WorkflowRun) -> dict[str, Any]:
    return {"id": run.id, "status": run.status, "agent": run.agent,
            "error": redact_text(run.error) if run.error else None,
            "output_refs": run.output_refs or {}, "usage": run.usage or {},
            "provider_meta": redact(run.provider_meta or {}),
            "started_at": iso(run.started_at), "finished_at": iso(run.finished_at)}
