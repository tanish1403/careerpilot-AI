"""Gateway implementing ModelGateway: policy routing, retries, fallback, budgets, usage."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.secrets import get_secret
from ..db.models import AgentConfig, Model, Provider, Setting, WorkflowRun
from .adapters import BaseAdapter, build_adapters, parse_json_output, schema_instruction  # noqa: F401
from .errors import (BudgetExceeded, CapabilityError, ConsentRequired, GatewayError, NoRouteError,
                     ProviderError, StructuredOutputError, scrub)
from .interface import (EmbedRequest, EmbedResult, GenerateRequest, GenerateResult, HealthResult,
                        TaskPolicy)

log = logging.getLogger("careerpilot.gateway")
_TRUE = (True, "true", "1", "yes", "on")


def is_local_provider(p: Provider) -> bool:
    if p.protocol == "ollama" or (p.extra or {}).get("local") is True:
        return True
    host = (urlparse(p.base_url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith(".local"):
        return True
    try:
        ip = ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def merge_usage(cur: dict, add: dict, model_key: str) -> dict:
    out = json.loads(json.dumps(cur or {}))
    for k in ("prompt_tokens", "completion_tokens"):
        out[k] = (out.get(k) or 0) + (add.get(k) or 0)
    out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    out["calls"] = out.get("calls", 0) + 1
    c = add.get("cost_usd")
    if c is None:
        out["unknown_cost_calls"] = out.get("unknown_cost_calls", 0) + 1
    else:
        out["cost_usd"] = round((out.get("cost_usd") or 0.0) + c, 8)
    out.setdefault("cost_usd", None)  # None = no call had a known cost; never invented
    bm = out.setdefault("by_model", {}).setdefault(
        model_key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": None})
    bm["calls"] += 1
    bm["prompt_tokens"] += add.get("prompt_tokens") or 0
    bm["completion_tokens"] += add.get("completion_tokens") or 0
    if c is not None:
        bm["cost_usd"] = round((bm["cost_usd"] or 0.0) + c, 8)
    return out


class Gateway:
    def __init__(self, db: Session, transport: httpx.AsyncBaseTransport | None = None,
                 sleep=None, backoff_base: float = 0.5, adapters: dict | None = None):
        self.db = db
        self.adapters: dict[str, BaseAdapter] = adapters or build_adapters(transport)
        self._sleep = sleep or asyncio.sleep
        self.backoff_base = backoff_base
        self._mem: dict[str, dict] = {}       # usage for runs without a WorkflowRun row
        self._mem_agent_cost: dict[str, float] = {}

    # ---- helpers ---------------------------------------------------------------------------
    def _setting(self, key: str, default=None):
        row = self.db.get(Setting, key)
        return default if row is None else row.value

    def allow_external(self) -> bool:
        row = self.db.get(Setting, "allow_external_llm")
        return (row.value in _TRUE) if row is not None else bool(get_settings().allow_external_llm)

    def _provider(self, provider_id: str) -> Provider:
        p = self.db.get(Provider, provider_id)
        if not p or p.deleted_at:
            raise NoRouteError(f"provider {provider_id} not found")
        return p

    def _key(self, p: Provider) -> str | None:
        return get_secret(self.db, p.secret_ref)

    def _adapter(self, p: Provider) -> BaseAdapter:
        a = self.adapters.get(p.protocol)
        if not a:
            raise CapabilityError(f"unsupported protocol {p.protocol!r}")
        return a

    def _price(self, p: Provider, model_id: str, pt: float | None, ct: float | None) -> float | None:
        table = self._setting("pricing") or {}
        e = table.get(f"{p.id}:{model_id}") or table.get(model_id)
        if not isinstance(e, dict) or pt is None and ct is None:
            return None
        try:
            return round((pt or 0) / 1000 * float(e["prompt_per_1k"])
                         + (ct or 0) / 1000 * float(e["completion_per_1k"]), 8)
        except (KeyError, TypeError, ValueError):
            return None

    # ---- provider ops ----------------------------------------------------------------------
    async def list_models(self, provider_id: str) -> list[dict]:
        p = self._provider(provider_id)
        key = self._key(p)
        try:
            return await self._adapter(p).list_models(p.base_url, key, p.extra or {},
                                                      timeout_s=p.timeout_s)
        except ProviderError as e:
            raise GatewayError(scrub(str(e), key)) from None

    async def health(self, provider_id: str) -> HealthResult:
        p = self._provider(provider_id)
        key = self._key(p)
        r = await self._adapter(p).health(p.base_url, key, p.timeout_s)
        return HealthResult(ok=r.ok, latency_ms=r.latency_ms, detail=scrub(r.detail or "", key))

    async def test_connection(self, provider_id: str) -> HealthResult:
        r = await self.health(provider_id)
        p = self._provider(provider_id)
        p.last_test_ok, p.last_test_at = r.ok, datetime.now(timezone.utc)
        self.db.flush()
        return r

    # ---- routing ---------------------------------------------------------------------------
    def _candidates(self, policy: TaskPolicy, need: list[str], est_tokens: int
                    ) -> tuple[list[tuple[Provider, Model]], list[str]]:
        skipped: list[str] = []
        pairs: list[Model] = []
        cfg = None
        if policy.agent:
            cfg = self.db.query(AgentConfig).filter_by(agent=policy.agent).first()
        if cfg and cfg.enabled is False:
            raise NoRouteError(f"agent {policy.agent} is disabled")
        if cfg and (cfg.primary_model_id or cfg.fallback_model_ids):
            for mid in [cfg.primary_model_id, *(cfg.fallback_model_ids or [])]:
                m = self.db.get(Model, mid) if mid else None
                if m and not m.deleted_at:
                    pairs.append(m)
        else:
            pairs = [m for m in self.db.query(Model).filter(Model.deleted_at.is_(None))
                     .order_by(Model.created_at).all()]
            pairs.sort(key=lambda m: (m.provider_id != policy.prefer_provider_id, not m.verified))
        out: list[tuple[Provider, Model]] = []
        allow_ext = self.allow_external()
        for m in pairs:
            p = self.db.get(Provider, m.provider_id)
            tag = f"{m.model_id}@{p.display_name if p else '?'}"
            if not p or p.deleted_at or not p.enabled or not m.enabled:
                skipped.append(f"{tag}: disabled")
                continue
            caps = m.capabilities or {}
            miss = [c for c in need if not caps.get(c)]
            if miss:
                skipped.append(f"{tag}: missing capability {','.join(miss)}")
                continue
            local = is_local_provider(p)
            if policy.local_only and not local:
                skipped.append(f"{tag}: local_only")
                continue
            if policy.sensitive_document and not local and not allow_ext:
                skipped.append(f"{tag}: consent")
                continue
            if policy.max_cost_usd is not None and not local:
                est = self._price(p, m.model_id, est_tokens, policy_max_out(policy))
                if est is None or est > policy.max_cost_usd:
                    skipped.append(f"{tag}: cost ceiling")
                    continue
            out.append((p, m))
        return out, skipped

    def _no_route(self, skipped: list[str]) -> GatewayError:
        if any(s.endswith(": consent") for s in skipped):
            return ConsentRequired("sensitive document requires explicit consent "
                                   "(allow_external_llm) before using a non-local provider")
        return NoRouteError("no model satisfies policy: " + "; ".join(skipped or ["no models"]))

    # ---- budgets / usage -------------------------------------------------------------------
    def usage(self, run_id: str) -> dict:
        row = self.db.get(WorkflowRun, run_id)
        if row is not None:
            return dict(row.usage or {})
        return dict(self._mem.get(run_id, {}))

    def _agent_spent(self, agent: str) -> float:
        rows = self.db.query(WorkflowRun).filter(WorkflowRun.agent == agent).all()
        return sum((r.usage or {}).get("cost_usd") or 0.0 for r in rows) + \
            self._mem_agent_cost.get(agent, 0.0)

    def _check_budget(self, policy: TaskPolicy, run_id: str | None, est: float | None) -> None:
        limits: list[tuple[str, float, float]] = []
        rb = self._setting("run_budget_usd")
        if run_id and isinstance(rb, (int, float)) and not isinstance(rb, bool):
            limits.append(("run", float(rb), self.usage(run_id).get("cost_usd") or 0.0))
        if policy.agent:
            cfg = self.db.query(AgentConfig).filter_by(agent=policy.agent).first()
            if cfg and cfg.budget_usd is not None:
                limits.append(("agent", cfg.budget_usd, self._agent_spent(policy.agent)))
        for kind, lim, spent in limits:
            if spent >= lim or (est is not None and spent + est > lim):
                raise BudgetExceeded(f"{kind} budget exceeded (limit ${lim:.4f}, spent ${spent:.4f})")

    def _persist(self, run_id: str | None, policy: TaskPolicy, usage: dict | None, model_key: str,
                 meta: dict) -> None:
        row = self.db.get(WorkflowRun, run_id) if run_id else None
        if usage is not None:
            if row is not None:
                row.usage = merge_usage(row.usage or {}, usage, model_key)
            else:
                key = run_id or "_none"
                self._mem[key] = merge_usage(self._mem.get(key, {}), usage, model_key)
                if policy.agent:
                    self._mem_agent_cost[policy.agent] = (
                        self._mem_agent_cost.get(policy.agent, 0.0) + (usage.get("cost_usd") or 0.0))
        if row is not None:
            row.provider_meta = {**(row.provider_meta or {}), **meta}
            self.db.flush()

    # ---- generate --------------------------------------------------------------------------
    async def generate(self, req: GenerateRequest, policy: TaskPolicy) -> GenerateResult:
        est_tokens = len(json.dumps(req.messages)) // 4
        cands, skipped = self._candidates(policy, list(policy.require), est_tokens)
        if not cands:
            raise self._no_route(skipped)
        attempts: list[dict] = []
        for idx, (p, m) in enumerate(cands):
            est = self._price(p, m.model_id, est_tokens, req.max_tokens or 1024)
            self._check_budget(policy, req.run_id, est)
            res, att, spent_tok = await self._try_model(p, m, req, policy)
            attempts.append(att)
            if res is None:
                if spent_tok:   # tokens burnt by invalid structured outputs still cost money
                    self._persist(req.run_id, policy, {**spent_tok, "cost_usd": self._price(
                        p, m.model_id, spent_tok.get("prompt_tokens"),
                        spent_tok.get("completion_tokens"))}, f"{p.id}:{m.model_id}", {})
                continue
            usage = {"prompt_tokens": res.usage.get("prompt_tokens"),
                     "completion_tokens": res.usage.get("completion_tokens")}
            usage["cost_usd"] = self._price(p, m.model_id, usage["prompt_tokens"],
                                            usage["completion_tokens"])
            res.usage = {**usage, "total_tokens": (usage["prompt_tokens"] or 0)
                         + (usage["completion_tokens"] or 0)}
            res.provider_id, res.model_id = p.id, m.model_id
            res.fallback_used = idx > 0 or len(attempts) > 1
            res.attempts = attempts
            self._persist(req.run_id, policy, usage, f"{p.id}:{m.model_id}", {
                "provider_id": p.id, "model_id": m.model_id, "fallback_used": res.fallback_used,
                "attempts": attempts[-20:], "agent": policy.agent})
            return res
        self._persist(req.run_id, policy, None, "", {"provider_id": None, "fallback_used": True,
                                                      "attempts": attempts[-20:]})
        raise GatewayError("all providers failed: " + "; ".join(
            f"{a['model_id']}: {a.get('error')}" for a in attempts), attempts)

    async def _try_model(self, p: Provider, m: Model, req: GenerateRequest, policy: TaskPolicy):
        adapter, key = self._adapter(p), self._key(p)
        timeout = min(p.timeout_s, policy.max_latency_s) if policy.max_latency_s else p.timeout_s
        att = {"provider_id": p.id, "model_id": m.model_id, "ok": False, "retries": 0}
        spent = {"prompt_tokens": 0, "completion_tokens": 0}
        messages, reasks, t0 = list(req.messages), 0, time.perf_counter()
        n = 0
        while True:
            try:
                r = await adapter.generate(p.base_url, key, m.model_id,
                                           req.model_copy(update={"messages": messages}),
                                           int(timeout), policy.json_schema)
                if policy.json_schema:
                    try:
                        r.parsed = parse_json_output(r.text, policy.json_schema)
                    except StructuredOutputError:
                        for k in spent:
                            spent[k] += r.usage.get(k) or 0
                        raise
                att.update(ok=True, latency_ms=round((time.perf_counter() - t0) * 1000, 1))
                return r, att, spent
            except StructuredOutputError as e:
                att["error"] = scrub(str(e), key)
                if reasks < 1:   # one corrective re-ask on the same model, then fail over
                    reasks += 1
                    att["retries"] += 1
                    messages = [*req.messages,
                                {"role": "user", "content": "Your previous reply was invalid ("
                                 + str(e)[:150] + "). Reply again with ONLY valid JSON matching "
                                 "the schema."}]
                    continue
                return None, att, spent
            except ProviderError as e:
                att["error"], att["status"] = scrub(str(e), key), e.status
                if e.retryable and n < p.max_retries:
                    n += 1
                    att["retries"] += 1
                    log.warning("retrying provider %s (%s)", p.id, att["error"])
                    await self._sleep(self.backoff_base * (2 ** (n - 1)))
                    continue
                log.warning("provider %s failed: %s", p.id, att["error"])
                return None, att, spent

    # ---- embed -----------------------------------------------------------------------------
    async def embed(self, req: EmbedRequest, policy: TaskPolicy) -> EmbedResult:
        need = list(dict.fromkeys([*policy.require, "embeddings"]))
        cands, skipped = self._candidates(policy, need, sum(len(s) for s in req.inputs) // 4)
        if not cands:
            raise self._no_route(skipped)
        attempts: list[dict] = []
        for p, m in cands:
            self._check_budget(policy, req.run_id, None)
            key, n = self._key(p), 0
            att = {"provider_id": p.id, "model_id": m.model_id, "ok": False, "retries": 0}
            attempts.append(att)
            while True:
                try:
                    r = await self._adapter(p).embed(p.base_url, key, m.model_id, req, p.timeout_s)
                    att["ok"] = True
                    r.provider_id, r.model_id = p.id, m.model_id
                    self._persist(req.run_id, policy, {"prompt_tokens": None,
                                                       "completion_tokens": None, "cost_usd": None},
                                  f"{p.id}:{m.model_id}", {})
                    return r
                except ProviderError as e:
                    att["error"] = scrub(str(e), key)
                    if e.retryable and n < p.max_retries:
                        n += 1
                        att["retries"] += 1
                        await self._sleep(self.backoff_base * (2 ** (n - 1)))
                        continue
                    break
        raise GatewayError("all embedding providers failed", attempts)


def policy_max_out(policy: TaskPolicy) -> int:
    return 1024
