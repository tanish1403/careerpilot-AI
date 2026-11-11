"""Durable workflow runner with human-approval pause/resume. Checkpoints live in the DB
(Checkpoint table) so a fresh runner instance (app restart) resumes exactly where the run
stopped. (LangGraph is installable but its checkpointer API would not map onto our Checkpoint
table without a custom saver; this small runner has the same semantics: node checkpoints,
interrupt-before-approval, resume-from-checkpoint.)"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..core.audit import audit
from ..core.redaction import redact
from ..db.models import Approval, Checkpoint, Workflow, WorkflowRun
from ..provider_gateway.errors import (BudgetExceeded, ConsentRequired, NoRouteError, scrub)
from .agents import AGENTS, AgentOutputError
from .supervisor import NON_RETRYABLE, TERMINAL, Supervisor
from .tools import TOOLS

log = logging.getLogger("careerpilot.workflows")
NO_RETRY = (*NON_RETRYABLE, ConsentRequired, BudgetExceeded, NoRouteError)


def now():
    return datetime.now(timezone.utc)


def validate_definition(defn: dict) -> list[str]:
    errs, seen = [], set()
    steps = defn.get("steps") if isinstance(defn, dict) else None
    if not isinstance(steps, list) or not steps:
        return ["definition.steps must be a non-empty list"]
    for i, s in enumerate(steps):
        sid = s.get("id") if isinstance(s, dict) else None
        if not sid or sid in seen:
            errs.append(f"step {i}: missing or duplicate id")
            continue
        seen.add(sid)
        t = s.get("type")
        if t == "agent":
            if s.get("agent") not in AGENTS:
                errs.append(f"step {sid}: unknown agent {s.get('agent')!r}")
            for g in s.get("grants", []) or []:
                if g not in TOOLS:
                    errs.append(f"step {sid}: unknown tool {g!r}")
        elif t != "approval":
            errs.append(f"step {sid}: type must be 'agent' or 'approval'")
    return errs


def resolve(v: Any, state: dict) -> Any:
    if isinstance(v, str) and v.startswith("$."):
        node: Any = {"inputs": state["inputs"], "steps": state["outputs"]}
        for part in v[2:].split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node
    if isinstance(v, dict):
        return {k: resolve(x, state) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x, state) for x in v]
    return v


def latest_checkpoint(db: Session, run_id: str) -> Checkpoint | None:
    rows = db.query(Checkpoint).filter_by(run_id=run_id).all()
    return max(rows, key=lambda c: (c.state or {}).get("seq", 0), default=None)


def decide_approval(db: Session, approval_id: str, grant: bool, actor: str | None,
                    comment: str | None = None) -> tuple[Approval, str | None]:
    ap = db.get(Approval, approval_id)
    if ap is None:
        raise LookupError("approval not found")
    if ap.status != "pending":
        raise ValueError(f"approval already {ap.status}")
    ap.status, ap.actor, ap.decided_at = ("granted" if grant else "denied"), actor, now()
    run_id = ap.subject_id if ap.subject_type == "workflow_run" else None
    audit(db, "approval.decided", actor=actor, subject_type="approval", subject_id=ap.id,
          detail={"grant": grant, "kind": ap.kind, "comment": comment})
    if run_id:
        run = db.get(WorkflowRun, run_id)
        if run:
            run.approval_actor = actor
            if not grant and run.status not in TERMINAL:
                run.status, run.error, run.finished_at = "cancelled", "approval denied", now()
    db.flush()
    return ap, run_id


class WorkflowRunner:
    def __init__(self, db: Session, gateway, sleep=None, backoff: float = 0.5):
        self.db, self.gateway = db, gateway
        self._sleep = sleep or asyncio.sleep
        self.backoff = backoff
        self.sup = Supervisor(db, gateway)

    # ---- lifecycle -----------------------------------------------------------------------
    def create(self, workflow_id: str, inputs: dict, idempotency_key: str | None = None
               ) -> WorkflowRun:
        wf = self.db.get(Workflow, workflow_id)
        if wf is None or wf.deleted_at:
            raise LookupError("workflow not found")
        if idempotency_key:
            ex = self.db.query(WorkflowRun).filter_by(
                workflow_id=workflow_id, idempotency_key=idempotency_key,
                parent_run_id=None).first()
            if ex:
                return ex
        run = WorkflowRun(workflow_id=workflow_id, status="pending", inputs=inputs,
                          idempotency_key=idempotency_key,
                          provider_meta={"schema_versions": {"workflow": str(
                              wf.definition.get("version", 1))}})
        self.db.add(run)
        self.db.flush()
        self._checkpoint(run, "start", {"seq": 0, "next_index": 0, "inputs": inputs, "outputs": {},
                                        "definition": wf.definition})
        self.db.commit()
        return run

    def _checkpoint(self, run: WorkflowRun, step: str, state: dict, awaiting: bool = False):
        self.db.add(Checkpoint(run_id=run.id, step=step, state=state, awaiting_approval=awaiting))
        self.db.flush()

    def pause(self, run_id: str) -> WorkflowRun:
        run = self.db.get(WorkflowRun, run_id)
        if run.status not in ("pending", "running"):
            raise ValueError(f"cannot pause a {run.status} run")
        run.status = "paused"
        audit(self.db, "run.paused", subject_type="run", subject_id=run.id)
        self.db.commit()
        return run

    def cancel(self, run_id: str) -> WorkflowRun:
        run = self.db.get(WorkflowRun, run_id)
        if run.status in TERMINAL:
            raise ValueError(f"run already {run.status}")
        run.status, run.finished_at = "cancelled", now()
        for ap in self.db.query(Approval).filter_by(subject_type="workflow_run",
                                                    subject_id=run.id, status="pending"):
            ap.status = "expired"
        for ch in self.db.query(WorkflowRun).filter_by(parent_run_id=run.id):
            if ch.status not in TERMINAL:
                ch.status = "cancelled"
        audit(self.db, "run.cancelled", subject_type="run", subject_id=run.id)
        self.db.commit()
        return run

    async def resume(self, run_id: str) -> WorkflowRun:
        """Continue a paused/pending run from its latest checkpoint (new runner instances OK)."""
        run = self.db.get(WorkflowRun, run_id)
        if run.status in TERMINAL:
            return run
        cp = latest_checkpoint(self.db, run_id)
        if cp is not None and cp.awaiting_approval:
            ap = self.db.get(Approval, cp.state.get("approval_id"))
            if ap is None or ap.status == "pending":
                raise ValueError("run is awaiting approval")
            if ap.status != "granted":
                return self.cancel(run_id) if run.status not in TERMINAL else run
            st = {**cp.state, "seq": cp.state["seq"] + 1}
            st.pop("approval_id", None)
            self._checkpoint(run, f"{cp.step}:approved", st)
        run.status = "running"
        self.db.commit()
        return await self.advance(run_id)

    async def advance(self, run_id: str) -> WorkflowRun:
        run = self.db.get(WorkflowRun, run_id)
        if run.status in TERMINAL or run.status == "paused":
            return run
        cp = latest_checkpoint(self.db, run_id)
        if cp is not None and cp.awaiting_approval:
            return run
        state = dict(cp.state)
        steps = state["definition"]["steps"]
        run.status, run.started_at = "running", run.started_at or now()
        self.db.commit()
        while state["next_index"] < len(steps):
            self.db.refresh(run)
            if run.status in ("paused", "cancelled"):
                return run
            step = steps[state["next_index"]]
            if step["type"] == "approval":
                ap = Approval(kind=step.get("kind", "workflow"), subject_type="workflow_run",
                              subject_id=run.id, status="pending",
                              snapshot=redact({"step": step["id"], "message": step.get("message"),
                                               "outputs": state["outputs"]}))
                self.db.add(ap)
                self.db.flush()
                state = {**state, "seq": state["seq"] + 1, "next_index": state["next_index"] + 1,
                         "approval_id": ap.id}
                self._checkpoint(run, step["id"], state, awaiting=True)
                run.status = "paused"
                audit(self.db, "workflow.awaiting_approval", subject_type="run",
                      subject_id=run.id, detail={"step": step["id"], "approval_id": ap.id})
                self.db.commit()
                return run
            try:
                out = await self._agent_step(run, step, state)
            except BaseException as e:   # noqa: BLE001
                run = self.db.get(WorkflowRun, run_id)
                if run.status != "cancelled":
                    run.status = "failed"
                run.error = scrub(f"step {step['id']}: {type(e).__name__}: {e}")
                run.finished_at = now()
                self._aggregate(run)
                self.db.commit()
                return run
            outputs = {**state["outputs"], step["id"]: out}
            state = {**state, "seq": state["seq"] + 1, "next_index": state["next_index"] + 1,
                     "outputs": outputs}
            self._checkpoint(run, step["id"], state)
            self._aggregate(run)
            self.db.commit()
        run.status, run.finished_at, run.error = "succeeded", now(), None
        run.output_refs = {"outputs": state["outputs"],
                           "steps": {c.idempotency_key.split(":", 1)[1]: c.id for c in
                                     self.db.query(WorkflowRun).filter_by(parent_run_id=run.id)
                                     if c.idempotency_key}}
        self._aggregate(run)
        self.db.commit()
        return run

    async def _agent_step(self, run: WorkflowRun, step: dict, state: dict) -> dict:
        payload = resolve(step.get("input", {}), state)
        child = self.sup.create_run(step["agent"], payload, parent=run,
                                    idempotency_key=f"{run.id}:{step['id']}")
        self.db.commit()
        tries = 1 + int(step.get("retries", 1))
        for n in range(tries):
            try:
                return await self.sup.execute_run(child.id, grants=step.get("grants"),
                                                  step=step["id"])
            except NO_RETRY:
                raise
            except Exception:   # noqa: BLE001
                if n == tries - 1:
                    raise
                for r in (self.db.get(WorkflowRun, child.id), self.db.get(WorkflowRun, run.id)):
                    r.retries = (r.retries or 0) + 1
                self.db.commit()
                await self._sleep(self.backoff * (2 ** n))
        raise RuntimeError("unreachable")  # pragma: no cover

    def _aggregate(self, run: WorkflowRun) -> None:
        tot = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": None,
               "unknown_cost_calls": 0, "by_model": {}}
        meta = dict(run.provider_meta or {})
        for c in self.db.query(WorkflowRun).filter_by(parent_run_id=run.id).all():
            u = c.usage or {}
            for k in ("prompt_tokens", "completion_tokens", "calls", "unknown_cost_calls"):
                tot[k] += u.get(k) or 0
            if u.get("cost_usd") is not None:
                tot["cost_usd"] = round((tot["cost_usd"] or 0.0) + u["cost_usd"], 8)
            for mk, mv in (u.get("by_model") or {}).items():
                b = tot["by_model"].setdefault(mk, {"calls": 0, "prompt_tokens": 0,
                                                    "completion_tokens": 0, "cost_usd": None})
                for k in ("calls", "prompt_tokens", "completion_tokens"):
                    b[k] += mv.get(k) or 0
                if mv.get("cost_usd") is not None:
                    b["cost_usd"] = round((b["cost_usd"] or 0.0) + mv["cost_usd"], 8)
            if c.provider_meta.get("provider_id"):
                meta["last_step"] = {k: c.provider_meta.get(k) for k in
                                     ("provider_id", "model_id", "fallback_used")}
        tot["total_tokens"] = tot["prompt_tokens"] + tot["completion_tokens"]
        run.usage, run.provider_meta = tot, meta


def run_in_background(kind: str, run_id: str) -> None:
    """Sync entry point for FastAPI BackgroundTasks (own session, own event loop)."""
    from ..db.session import session_scope
    from ..provider_gateway import deps
    from .mock import MockGateway
    with session_scope() as db:
        gw = MockGateway() if deps.mock_mode(db) else deps.make_gateway(db)
        runner = WorkflowRunner(db, gw, sleep=deps.sleep)
        if kind == "agent":
            try:
                asyncio.run(runner.sup.execute_run(run_id))
            except Exception:   # noqa: BLE001 - already recorded on the run row
                log.warning("agent run %s failed", run_id)
        elif kind == "resume":
            asyncio.run(runner.resume(run_id))
        else:
            asyncio.run(runner.advance(run_id))
