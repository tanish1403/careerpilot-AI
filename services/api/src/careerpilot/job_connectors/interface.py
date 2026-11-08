"""Job source adapter contract. Lane C implements. No auth/CAPTCHA/anti-bot bypass, ever."""
from __future__ import annotations
from datetime import datetime
from typing import Protocol
from pydantic import BaseModel, Field


class RawJob(BaseModel):
    """Normalized job as produced by a connector (before dedupe/persist)."""
    source_kind: str
    external_id: str
    source_url: str
    canonical_url: str
    title: str
    company: str
    location: str | None = None
    work_mode: str = "unknown"
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    salary_text: str | None = None
    seniority: str | None = None
    posted_at: datetime | None = None
    collection_method: str = "public_api"
    raw: dict = Field(default_factory=dict)


class ConnectorResult(BaseModel):
    jobs: list[RawJob] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    complete: bool = True   # True => the source returned its full open-job list (enables closed detection)


class JobConnector(Protocol):
    kind: str
    permitted_usage: str      # documented usage + limitations (surfaced in UI/docs)
    async def fetch(self, config: dict) -> ConnectorResult: ...
