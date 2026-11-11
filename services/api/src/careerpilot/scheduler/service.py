"""Scheduler: APScheduler BackgroundScheduler over ScheduledTask rows. Idempotent via TaskRun
(task_id, period_key). Lane A reads `is_running()`."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.audit import audit
from ..core.redaction import redact_text
from ..db.base import utcnow
from ..db.models import Notification, ScheduledTask, Setting, TaskRun
from . import tasks as tasks_mod
from .tasks import assert_no_submit_kind

log = logging.getLogger("careerpilot.scheduler")
CATCHUP_WINDOW_HOURS = 48
_svc: "SchedulerService | None" = None


def kinds() -> list[str]:
    assert_no_submit_kind(tasks_mod.HANDLERS)
    return sorted(tasks_mod.HANDLERS)


def make_trigger(cron: str, tz: str) -> CronTrigger:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"unknown timezone: {tz!r}") from None
    if len(cron.split()) != 5:
        raise ValueError("cron must have 5 fields (minute hour day month weekday)")
    try:
        return CronTrigger.from_crontab(cron, timezone=zone)
    except (ValueError, KeyError) as e:
        raise ValueError(f"invalid cron expression: {e}") from None


def validate_task(kind: str, cron: str, tz: str) -> None:
    if kind not in tasks_mod.HANDLERS:
        raise ValueError(f"unknown task kind {kind!r}; allowed: {', '.join(kinds())}")
    make_trigger(cron, tz)


def fire_times(cron: str, tz: str, start: datetime, end: datetime, limit: int = 500) -> list[datetime]:
    trig, out, prev, cur = make_trigger(cron, tz), [], None, start
    while len(out) < limit:
        nxt = trig.get_next_fire_time(prev, cur)
        if nxt is None or nxt > end:
            break
        out.append(nxt)
        prev, cur = nxt, nxt
    return out


def period_key(fire: datetime) -> str:
    return fire.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%MZ")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo("UTC"))


def execute(db: Session, task: ScheduledTask, key: str, *, now: datetime | None = None,
            retry: bool = False) -> TaskRun:
    """Run `task` for `key` exactly once. Existing succeeded/running/failed runs are returned untouched
    unless `retry` is set for a failed one."""
    now = now or utcnow()
    run = db.query(TaskRun).filter(TaskRun.task_id == task.id, TaskRun.period_key == key).first()
    if run is not None and not (retry and run.status == "failed"):
        return run
    if run is None:
        run = TaskRun(task_id=task.id, period_key=key, status="running", started_at=now, result={})
        try:
            with db.begin_nested():
                db.add(run)
                db.flush()
        except IntegrityError:   # concurrent worker claimed this period
            return db.query(TaskRun).filter(TaskRun.task_id == task.id, TaskRun.period_key == key).one()
    else:
        run.status, run.error, run.started_at, run.finished_at = "running", None, now, None
        run.result = {**(run.result or {}), "attempts": (run.result or {}).get("attempts", 1) + 1}
    handler = tasks_mod.HANDLERS[task.kind]
    try:
        with db.begin_nested():
            res = handler(db, task, now)
        run.status, run.result = "succeeded", {**(run.result or {}), **(res or {})}
    except Exception as e:  # noqa: BLE001 - failures must be recorded, never crash the scheduler
        run.status, run.error = "failed", redact_text(f"{type(e).__name__}: {e}")
        run.result = {**(run.result or {}), "attempts": (run.result or {}).get("attempts", 1)}
        db.add(Notification(kind="scheduler_failure", title=f"Scheduled task failed: {task.name}",
                            body=run.error, payload={"task_id": task.id, "run_id": run.id}))
    run.finished_at = utcnow()
    task.last_run_at = run.finished_at
    audit(db, "scheduler.run", actor="scheduler", subject_type="scheduled_task", subject_id=task.id,
          detail={"kind": task.kind, "period_key": key, "status": run.status})
    db.flush()
    return run


def run_now(db: Session, task: ScheduledTask) -> TaskRun:
    return execute(db, task, "manual:" + uuid.uuid4().hex[:12])


def catch_up(db: Session, now: datetime | None = None, window_hours: int = CATCHUP_WINDOW_HOURS) -> list[TaskRun]:
    """Run missed scheduled fires since max(task creation, now - window); at most `catchup_max`
    (default 1) most-recent misses per task. Idempotent through period keys."""
    now = now or utcnow()
    runs = []
    for t in db.query(ScheduledTask).filter(ScheduledTask.deleted_at.is_(None), ScheduledTask.enabled.is_(True)):
        start = max(_aware(t.created_at), now - timedelta(hours=window_hours))
        times = fire_times(t.cron, t.timezone, start, now)
        done = {r.period_key for r in db.query(TaskRun).filter(TaskRun.task_id == t.id)}
        last = max((k for k in done if not k.startswith("manual:")), default="")   # never walk backwards
        missed = [f for f in times if period_key(f) not in done and period_key(f) > last]
        for f in missed[-int((t.config or {}).get("catchup_max", 1)):]:
            runs.append(execute(db, t, period_key(f), now=now))
    return runs


def is_paused(db: Session) -> bool:
    row = db.get(Setting, "scheduler_paused")
    return bool(row and row.value is True)


def set_paused(db: Session, paused: bool) -> None:
    row = db.get(Setting, "scheduler_paused")
    if row is None:
        db.add(Setting(key="scheduler_paused", value=paused))
    else:
        row.value = paused
    db.flush()
    if _svc is not None and _svc.running:
        _svc.pause() if paused else _svc.resume()


def _job(task_id: str) -> None:
    from ..db.session import session_scope
    with session_scope() as db:
        t = db.get(ScheduledTask, task_id)
        if t is None or t.deleted_at is not None or not t.enabled or is_paused(db):
            return
        now = utcnow()
        times = fire_times(t.cron, t.timezone, now - timedelta(days=8), now)
        execute(db, t, period_key(times[-1]) if times else period_key(now.replace(second=0, microsecond=0)), now=now)


class SchedulerService:
    def __init__(self) -> None:
        self.sched: BackgroundScheduler | None = None
        self.paused = False

    @property
    def running(self) -> bool:
        return bool(self.sched and self.sched.running)

    def start(self, run_catchup: bool = True) -> None:
        from ..db.session import session_scope
        if self.running:
            return
        self.sched = BackgroundScheduler(timezone=ZoneInfo("UTC"))
        with session_scope() as db:
            self.paused = is_paused(db)
        self.sched.start(paused=self.paused)
        self.sync()
        if run_catchup and not self.paused:
            try:
                with session_scope() as db:
                    catch_up(db)
            except Exception:  # noqa: BLE001
                log.exception("missed-run catch-up failed")

    def stop(self) -> None:
        if self.sched is not None and self.sched.running:
            self.sched.shutdown(wait=False)
        self.sched = None

    def sync(self) -> None:
        """Make APScheduler jobs mirror enabled ScheduledTask rows."""
        from ..db.session import session_scope
        if not self.running:
            return
        for j in self.sched.get_jobs():
            j.remove()
        with session_scope() as db:
            for t in db.query(ScheduledTask).filter(ScheduledTask.deleted_at.is_(None),
                                                    ScheduledTask.enabled.is_(True)):
                try:
                    self.sched.add_job(_job, make_trigger(t.cron, t.timezone), args=[t.id], id=t.id,
                                       coalesce=True, max_instances=1, misfire_grace_time=3600)
                except ValueError:
                    log.warning("task %s has invalid schedule; skipped", t.id)

    def pause(self) -> None:
        self.paused = True
        if self.running:
            self.sched.pause()

    def resume(self) -> None:
        self.paused = False
        if self.running:
            self.sched.resume()

    def next_runs(self) -> dict[str, str | None]:
        if not self.running:
            return {}
        return {j.id: (j.next_run_time.isoformat() if j.next_run_time else None) for j in self.sched.get_jobs()}


def get() -> SchedulerService:
    global _svc
    if _svc is None:
        _svc = SchedulerService()
    return _svc


def is_running() -> bool:
    return _svc is not None and _svc.running


def notify_changed() -> None:
    if is_running():
        _svc.sync()
