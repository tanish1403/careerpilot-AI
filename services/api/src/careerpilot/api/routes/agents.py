"""Agents: list/config/run (contract Lane D)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ...agent_workflows.agents import AGENTS
from ...agent_workflows.runner import run_in_background
from ...agent_workflows.supervisor import Supervisor
from ...core.audit import audit
from ...core.auth import current_user
from ...core.system.runs import run_to_dict
from ...db.models import AgentConfig, Model
from ...db.session import get_db
from ...provider_gateway import hooks

router = APIRouter()
hooks.install()   # Lane B hooks -> gateway (consent-gated); idempotent


class AgentConfigIn(BaseModel):
    enabled: bool = True
    primary_model_id: str | None = None
    fallback_model_ids: list[str] = Field(default_factory=list)
    budget_usd: float | None = Field(None, ge=0)


class AgentConfigBulk(AgentConfigIn):
    agent: str


def _cfg(db: Session, name: str) -> AgentConfig | None:
    return db.query(AgentConfig).filter_by(agent=name).first()


def _out(db: Session, name: str) -> dict:
    a, c = AGENTS[name], _cfg(db, name)
    return {"name": name, "version": a.version, "description": a.description,
            "permissions": a.permissions.model_dump(),
            "input_schema": a.input_model.model_json_schema(),
            "output_schema": a.output_model.model_json_schema(),
            "config": {"enabled": c.enabled if c else True,
                       "primary_model_id": c.primary_model_id if c else None,
                       "fallback_model_ids": (c.fallback_model_ids or []) if c else [],
                       "budget_usd": c.budget_usd if c else None}}


def _apply(db: Session, name: str, body: AgentConfigIn) -> None:
    if name not in AGENTS:
        raise HTTPException(404, "Unknown agent")
    for mid in [body.primary_model_id, *body.fallback_model_ids]:
        if mid and db.get(Model, mid) is None:
            raise HTTPException(422, f"unknown model id {mid}")
    c = _cfg(db, name)
    if c is None:
        c = AgentConfig(agent=name)
        db.add(c)
    c.enabled, c.primary_model_id = body.enabled, body.primary_model_id
    c.fallback_model_ids, c.budget_usd = body.fallback_model_ids, body.budget_usd
    db.flush()
    audit(db, "agent.config_updated", actor="user", subject_type="agent", subject_id=name,
          detail=body.model_dump())


@router.get("/agents")
def list_agents(db: Session = Depends(get_db), _=Depends(current_user)):
    return {"items": [_out(db, n) for n in AGENTS], "total": len(AGENTS)}


@router.put("/agents")
def put_agents(body: list[AgentConfigBulk], db: Session = Depends(get_db),
               _=Depends(current_user)):
    for b in body:
        _apply(db, b.agent, b)
    return list_agents(db)


@router.get("/agents/{name}/config")
def get_config(name: str, db: Session = Depends(get_db), _=Depends(current_user)):
    if name not in AGENTS:
        raise HTTPException(404, "Unknown agent")
    return _out(db, name)["config"]


@router.put("/agents/{name}/config")
def put_config(name: str, body: AgentConfigIn, db: Session = Depends(get_db),
               _=Depends(current_user)):
    _apply(db, name, body)
    return _out(db, name)["config"]


@router.post("/agents/{name}/run", status_code=202)
def run_agent(name: str, body: dict[str, Any], bg: BackgroundTasks, db: Session = Depends(get_db),
              _=Depends(current_user), idempotency_key: str | None = Header(None)):
    agent = AGENTS.get(name)
    if agent is None:
        raise HTTPException(404, "Unknown agent")
    cfg = _cfg(db, name)
    if cfg is not None and not cfg.enabled:
        raise HTTPException(409, f"agent {name} is disabled")
    payload = body.get("input", body) if isinstance(body.get("input"), dict) else body
    try:
        agent.input_model.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_input=False, include_url=False)) from None
    run = Supervisor(db, None).create_run(name, payload, idempotency_key=idempotency_key)
    fresh = run.status == "pending"
    db.commit()
    if fresh:
        bg.add_task(run_in_background, "agent", run.id)
    return run_to_dict(run) | {"id": run.id}
