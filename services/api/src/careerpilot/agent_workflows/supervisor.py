"""Supervisor: dispatches agents with per-step tool grants. It issues ToolGrants from policy
(agent permissions intersected with the step's requested grants); nothing retrieved from jobs,
pages or documents can widen them."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..core.audit import audit
from ..core.redaction import redact
from ..db.models import AgentConfig, WorkflowRun
from ..provider_gateway.errors import scrub
from .agents import AGENTS, AgentOutputError, BaseAgent, GrantedContext
from .interface import AgentPermissions
from .tools import TOOLS, ToolBroker, ToolGrant, permits

log = logging.getLogger("careerpilot.agents")
TERMINAL = ("succeeded", "failed", "cancelled")
NON_RETRYABLE = (PermissionError, ValidationError, AgentOutputError, LookupError)


class AgentDisabled(PermissionError):
    pass


class BoundGateway:
    """Gateway handle for one agent run: agent name and run id are forced, nothing else exposed."""

    def __init__(self, gw, agent: str, run_id: str):
        self._gw, self._agent, self._run = gw, agent, run_id

    async def generate(self, req, policy):
        return await self._gw.generate(req.model_copy(update={"run_id": self._run}),
                                       policy.model_copy(update={"agent": self._agent}))

    async def embed(self, req, policy):
        return await self._gw.embed(req.model_copy(update={"run_id": self._run}),
                                    policy.model_copy(update={"agent": self._agent}))


def source_ids(payload: dict) -> dict:
    out = {}
    for k, v in payload.items():
        if k.endswith("_id") and isinstance(v, str):
            out[k] = v
        elif k.endswith("_ids") and isinstance(v, list):
            out[k] = [x for x in v if isinstance(x, str)]
    return out


def now():
    return datetime.now(timezone.utc)


class Supervisor:
    def __init__(self, db: Session, gateway, agents: dict[str, BaseAgent] | None = None):
        self.db, self.gateway, self.agents = db, gateway, agents or AGENTS

    def grant_for(self, agent: BaseAgent, requested: Iterable[str] | None, step: str = "main",
                  run_id: str | None = None) -> ToolGrant:
        names = list(agent.default_grants if requested is None else requested)
        perm: AgentPermissions = agent.permissions
        ok = {n for n in names if n in TOOLS and permits(perm, TOOLS[n])}
        for n in sorted(set(names) - ok):
            audit(self.db, "tool.grant_clipped", actor="supervisor", subject_type="run",
                  subject_id=run_id, detail={"agent": agent.name, "tool": n, "step": step})
        return ToolGrant(agent=agent.name, step=step, tools=frozenset(ok))

    async def dispatch(self, agent_name: str, payload: dict, *, run_id: str,
                       workflow_run_id: str | None = None, step: str = "main",
                       grants: Iterable[str] | None = None) -> dict:
        agent = self.agents.get(agent_name)
        if agent is None:
            raise LookupError(f"unknown agent {agent_name!r}")
        cfg = self.db.query(AgentConfig).filter_by(agent=agent_name).first()
        if cfg is not None and not cfg.enabled:
            raise AgentDisabled(f"agent {agent_name} is disabled")
        inp = agent.input_model.model_validate(payload)
        ctx = GrantedContext(run_id=run_id, workflow_run_id=workflow_run_id, db=None,
                             gateway=BoundGateway(self.gateway, agent_name, run_id),
                             tools=ToolBroker(self.db, self.grant_for(agent, grants, step, run_id),
                                              run_id))
        out = await agent.run(ctx, inp)
        return agent.output_model.model_validate(out.model_dump()).model_dump()

    # ---- persisted runs ------------------------------------------------------------------
    def create_run(self, agent: str, payload: dict, *, parent: WorkflowRun | None = None,
                   idempotency_key: str | None = None, workflow_id: str | None = None,
                   ) -> WorkflowRun:
        if idempotency_key:
            ex = self.db.query(WorkflowRun).filter_by(
                idempotency_key=idempotency_key, agent=agent).first()
            if ex:
                return ex
        a = self.agents[agent]
        row = WorkflowRun(agent=agent, agent_version=a.version, status="pending", inputs=payload,
                          parent_run_id=parent.id if parent else None,
                          workflow_id=workflow_id or (parent.workflow_id if parent else None),
                          idempotency_key=idempotency_key,
                          provider_meta={"schema_versions": {"agent": a.version, "input": "1",
                                                              "output": "1"}})
        self.db.add(row)
        self.db.flush()
        return row

    async def execute_run(self, run_id: str, grants: Iterable[str] | None = None,
                          step: str = "main") -> dict:
        row = self.db.get(WorkflowRun, run_id)
        if row.status in ("cancelled", "succeeded"):
            return (row.output_refs or {}).get("output", {})
        row.status, row.started_at = "running", row.started_at or now()
        self.db.commit()
        try:
            out = await self.dispatch(row.agent, row.inputs, run_id=row.id,
                                      workflow_run_id=row.parent_run_id, step=step, grants=grants)
        except BaseException as e:   # noqa: BLE001 - recorded, then re-raised
            row = self.db.get(WorkflowRun, run_id)
            if row.status != "cancelled":
                row.status = "failed"
            row.error = scrub(f"{type(e).__name__}: {e}")
            row.finished_at = now()
            if isinstance(e, PermissionError):
                audit(self.db, "agent.permission_denied", actor=f"agent:{row.agent}",
                      subject_type="run", subject_id=row.id, detail={"error": row.error})
            self.db.commit()
            raise
        row = self.db.get(WorkflowRun, run_id)
        row.status, row.finished_at, row.error = "succeeded", now(), None
        row.output_refs = {"output": redact_keep(out), "source_ids": source_ids(row.inputs or {})}
        self.db.commit()
        return out


def redact_keep(out: dict) -> dict:
    """Outputs are stored as-is (local DB) except secret-looking keys."""
    from ..core.redaction import SENSITIVE_KEYS
    return {k: ("[REDACTED]" if SENSITIVE_KEYS.search(k) else v) for k, v in out.items()}
