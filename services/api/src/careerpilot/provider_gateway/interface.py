"""Provider-neutral model gateway contract (ARCHITECTURE section 5). Lane D implements."""
from __future__ import annotations
from typing import Any, Protocol
from pydantic import BaseModel, Field


class ModelCapabilities(BaseModel):
    chat: bool = True
    structured_output: bool = False
    tool_calling: bool = False
    vision: bool = False
    embeddings: bool = False
    streaming: bool = False
    context_length: int | None = None
    protocol: str = "openai_compatible"
    verified: bool = False   # declared vs verified; never infer from model name alone


class TaskPolicy(BaseModel):
    task_type: str                        # e.g. "resume_tailor", "job_parse"
    agent: str | None = None
    require: list[str] = Field(default_factory=list)   # capability names required
    max_cost_usd: float | None = None
    max_latency_s: float | None = None
    prefer_provider_id: str | None = None
    local_only: bool = False
    json_schema: dict | None = None       # structured-output contract; fallbacks must honor it
    sensitive_document: bool = False      # consent gate: external providers need allow_external_llm


class GenerateRequest(BaseModel):
    messages: list[dict[str, Any]]
    temperature: float = 0.2
    max_tokens: int | None = None
    run_id: str | None = None


class GenerateResult(BaseModel):
    text: str
    parsed: dict | list | None = None     # validated against policy.json_schema when given
    provider_id: str
    model_id: str
    fallback_used: bool = False
    attempts: list[dict] = Field(default_factory=list)  # provider/model/error per attempt (redacted)
    usage: dict = Field(default_factory=dict)           # prompt_tokens, completion_tokens, cost_usd?


class EmbedRequest(BaseModel):
    inputs: list[str]
    run_id: str | None = None


class EmbedResult(BaseModel):
    vectors: list[list[float]]
    provider_id: str
    model_id: str


class HealthResult(BaseModel):
    ok: bool
    latency_ms: float | None = None
    detail: str | None = None


class ProviderAdapter(Protocol):
    """One adapter per wire protocol (openai_compatible, ollama, anthropic, gemini)."""
    protocol: str
    async def list_models(self, base_url: str, api_key: str | None, extra: dict) -> list[dict]: ...
    async def generate(self, base_url: str, api_key: str | None, model_id: str,
                       req: GenerateRequest, timeout_s: int, json_schema: dict | None) -> GenerateResult: ...
    async def embed(self, base_url: str, api_key: str | None, model_id: str,
                    req: EmbedRequest, timeout_s: int) -> EmbedResult: ...
    async def health(self, base_url: str, api_key: str | None, timeout_s: int) -> HealthResult: ...


class ModelGateway(Protocol):
    async def list_models(self, provider_id: str) -> list[dict]: ...
    async def test_connection(self, provider_id: str) -> HealthResult: ...
    async def generate(self, req: GenerateRequest, policy: TaskPolicy) -> GenerateResult: ...
    async def embed(self, req: EmbedRequest, policy: TaskPolicy) -> EmbedResult: ...
    async def health(self, provider_id: str) -> HealthResult: ...
    def usage(self, run_id: str) -> dict: ...
