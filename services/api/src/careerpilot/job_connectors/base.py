from __future__ import annotations

import re
from typing import Any

import httpx

from .errors import ConfigError
from .http import HttpFetcher, RateLimiter, Sleep

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}$")


class BaseConnector:
    kind = ""
    label = ""
    permitted_usage = ""
    config_schema: dict[str, Any] = {}

    def __init__(self, *, client: httpx.AsyncClient | None = None, limiter: RateLimiter | None = None,
                 sleep: Sleep | None = None, max_retries: int = 3, backoff_base: float = 1.0,
                 timeout_s: float = 20.0) -> None:
        self.client, self.limiter, self.sleep = client, limiter, sleep
        self.max_retries, self.backoff_base, self.timeout_s = max_retries, backoff_base, timeout_s

    def http(self) -> HttpFetcher:
        return HttpFetcher(self.client, limiter=self.limiter, sleep=self.sleep,
                           max_retries=self.max_retries, backoff_base=self.backoff_base,
                           timeout_s=self.timeout_s)

    def validate_config(self, config: dict) -> dict:
        return dict(config or {})

    @staticmethod
    def token(config: dict, key: str) -> str:
        v = str((config or {}).get(key) or "").strip()
        if not _TOKEN.match(v):
            raise ConfigError(f"config.{key} is required (letters, digits, '-', '_', '.')")
        return v

    @staticmethod
    def display_name(config: dict, token: str) -> str:
        return (config.get("company_name") or token.replace("-", " ").replace("_", " ").title()).strip()
