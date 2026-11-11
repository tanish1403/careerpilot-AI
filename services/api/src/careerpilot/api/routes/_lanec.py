"""Shared helpers for Lane C routes (underscore module: not auto-mounted)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from ...core.enums import RunStatus
from ...core.system.runs import fail_run, finish_run, mark_running, start_run
from ...db.session import session_scope


def iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + ("+00:00" if dt.tzinfo is None else "")


def launch_run(db: Session, bg: BackgroundTasks, agent: str, inputs: dict,
               work: Callable[[Session], dict[str, Any]]) -> dict:
    """Create a pending run, commit it, and execute `work(db)` in a background task."""
    run = start_run(db, agent, inputs, status=RunStatus.PENDING.value)
    db.commit()
    run_id = run.id

    def _exec() -> None:
        with session_scope() as s:
            r = s.get(type(run), run_id)
            mark_running(s, r)
        try:
            with session_scope() as s:
                out = work(s)
            with session_scope() as s:
                finish_run(s, s.get(type(run), run_id), output_refs=out)
        except Exception as e:  # noqa: BLE001
            with session_scope() as s:
                fail_run(s, s.get(type(run), run_id), e)

    bg.add_task(_exec)
    return {"run_id": run_id, "status": "pending"}
