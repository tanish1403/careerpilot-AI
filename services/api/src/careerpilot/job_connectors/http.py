"""Polite HTTP: per-source rate limiter, retries with exponential backoff, timeouts, honest
User-Agent. Public endpoints only: no credentials, cookies or challenge solving are ever sent."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from .errors import BlockedError, ConnectorHTTPError

USER_AGENT = "CareerPilotAI/0.1 (+self-hosted personal job-search assistant; honours robots.txt)"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BYTES = 10 * 1024 * 1024
Sleep = Callable[[float], Awaitable[None]]


@dataclass
class Runtime:
    """Process-wide defaults; tests override transport/sleep/clock with configure_runtime()."""
    transport: httpx.AsyncBaseTransport | None = None
    sleep: Sleep = asyncio.sleep
    clock: Callable[[], float] = time.monotonic
    limiters: dict[str, "RateLimiter"] = field(default_factory=dict)


RUNTIME = Runtime()


def configure_runtime(*, transport=None, sleep: Sleep | None = None, clock=None) -> None:
    RUNTIME.transport = transport
    if sleep is not None:
        RUNTIME.sleep = sleep
    if clock is not None:
        RUNTIME.clock = clock
    RUNTIME.limiters.clear()


def reset_runtime() -> None:
    RUNTIME.transport = None
    RUNTIME.sleep = asyncio.sleep
    RUNTIME.clock = time.monotonic
    RUNTIME.limiters.clear()


class RateLimiter:
    """Spaces requests at least 60/per_min seconds apart (first request is immediate)."""

    def __init__(self, per_min: float, *, clock=None, sleep: Sleep | None = None) -> None:
        self.per_min = per_min
        self.interval = 60.0 / per_min if per_min and per_min > 0 else 0.0
        self._clock = clock or RUNTIME.clock
        self._sleep = sleep or RUNTIME.sleep
        self._next: float | None = None

    async def acquire(self) -> float:
        now = self._clock()
        start = now if self._next is None else max(now, self._next)
        self._next = start + self.interval
        wait = start - now
        if wait > 0:
            await self._sleep(wait)
        return max(wait, 0.0)


def get_limiter(key: str, per_min: float) -> RateLimiter:
    cur = RUNTIME.limiters.get(key)
    if cur is None or cur.per_min != per_min:
        cur = RateLimiter(per_min)
        RUNTIME.limiters[key] = cur
    return cur


def make_client(timeout_s: float = 20.0, transport=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport or RUNTIME.transport, follow_redirects=True,
        timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"})


class HttpFetcher:
    def __init__(self, client: httpx.AsyncClient | None = None, *, limiter: RateLimiter | None = None,
                 sleep: Sleep | None = None, max_retries: int = 3, backoff_base: float = 1.0,
                 backoff_max: float = 30.0, timeout_s: float = 20.0) -> None:
        self._own = client is None
        self.client = client or make_client(timeout_s)
        self.limiter = limiter
        self.sleep = sleep or RUNTIME.sleep
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.requests = 0

    async def aclose(self) -> None:
        if self._own:
            await self.client.aclose()

    async def __aenter__(self) -> "HttpFetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def _delay(self, attempt: int, resp: httpx.Response | None) -> float:
        d = min(self.backoff_base * (2 ** attempt), self.backoff_max)
        if resp is not None and "retry-after" in resp.headers:
            try:
                d = max(d, min(float(resp.headers["retry-after"]), self.backoff_max))
            except ValueError:
                pass
        return d

    async def request(self, method: str, url: str, **kw) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.limiter:
                await self.limiter.acquire()
            resp: httpx.Response | None = None
            try:
                self.requests += 1
                resp = await self.client.request(method, url, **kw)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = ConnectorHTTPError(f"network error ({type(e).__name__}) for {_host(url)}",
                                          retryable=True)
            else:
                if len(resp.content) > MAX_BYTES:
                    raise ConnectorHTTPError("response too large; refusing to process")
                if resp.status_code in RETRY_STATUS:
                    last = ConnectorHTTPError(f"HTTP {resp.status_code} from {_host(url)}",
                                              resp.status_code, retryable=True)
                elif resp.status_code in (401, 403):
                    raise BlockedError(
                        f"{_host(url)} refused access (HTTP {resp.status_code}). The page needs "
                        "authentication or blocks automated access; CareerPilot does not bypass "
                        "this. Open the link yourself to apply at the source.", url)
                elif resp.status_code == 404 or resp.status_code == 410:
                    raise ConnectorHTTPError(f"not found (HTTP {resp.status_code}) at {_host(url)}",
                                             resp.status_code)
                elif resp.status_code >= 400:
                    raise ConnectorHTTPError(f"HTTP {resp.status_code} from {_host(url)}",
                                             resp.status_code)
                else:
                    return resp
            if attempt < self.max_retries:
                await self.sleep(self._delay(attempt, resp))
        assert last is not None
        raise last

    async def get(self, url: str, **kw) -> httpx.Response:
        return await self.request("GET", url, **kw)

    async def get_json(self, url: str, **kw):
        resp = await self.get(url, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise ConnectorHTTPError(f"invalid JSON from {_host(url)}") from e


def _host(url: str) -> str:
    return httpx.URL(url).host or url
