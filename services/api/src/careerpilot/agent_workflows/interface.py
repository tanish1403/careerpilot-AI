"""Typed agent contract. Each agent: explicit permissions, typed IO, no ambient access."""
from __future__ import annotations
from typing import Generic, TypeVar, Protocol
from pydantic import BaseModel

I = TypeVar("I", bound=BaseModel)
O = TypeVar("O", bound=BaseModel)


class AgentPermissions(BaseModel):
    reads: list[str] = []      # e.g. ["documents", "profile_facts"]
    writes: list[str] = []     # e.g. ["profile_facts:proposed"]
    network: bool = False
    browser: bool = False
    can_submit: bool = False   # only ever True for none; submission is a separate gated action


class Agent(Protocol, Generic[I, O]):
    name: str
    version: str
    permissions: AgentPermissions
    input_model: type[I]
    output_model: type[O]
    async def run(self, ctx: "AgentContext", payload: I) -> O: ...


class AgentContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    run_id: str
    workflow_run_id: str | None = None
    db: object = None          # SQLAlchemy Session, scoped to this step
    gateway: object = None     # ModelGateway
