"""Providers, models, presets, usage. No endpoint ever returns a secret value."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user
from ...core.secrets import delete_secret, has_secret, set_secret
from ...db.models import Model, Provider, Setting, WorkflowRun
from ...db.session import get_db
from ...provider_gateway import deps
from ...provider_gateway.errors import GatewayError, scrub
from ...provider_gateway.gateway import is_local_provider
from ...provider_gateway.presets import DEFAULT_PRESETS

router = APIRouter()
PROTOCOLS = ("openai_compatible", "ollama", "anthropic")
CAPS = ("chat", "structured_output", "tool_calling", "vision", "embeddings", "streaming")


def _secret_name(pid: str) -> str:
    return f"provider:{pid}"


def provider_out(db: Session, p: Provider) -> dict:
    return {"id": p.id, "display_name": p.display_name, "protocol": p.protocol,
            "base_url": p.base_url, "enabled": p.enabled, "timeout_s": p.timeout_s,
            "max_retries": p.max_retries, "extra": p.extra or {}, "local": is_local_provider(p),
            "has_secret": has_secret(db, p.secret_ref), "last_test_ok": p.last_test_ok,
            "last_test_at": p.last_test_at.isoformat() if p.last_test_at else None,
            "created_at": p.created_at.isoformat()}


def model_out(m: Model) -> dict:
    return {"id": m.id, "provider_id": m.provider_id, "model_id": m.model_id,
            "capabilities": m.capabilities or {}, "verified": m.verified, "enabled": m.enabled}


class ProviderIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    protocol: str
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = None          # write-only
    enabled: bool = True
    timeout_s: int = Field(60, ge=1, le=600)
    max_retries: int = Field(2, ge=0, le=10)
    extra: dict = Field(default_factory=dict)


class ProviderPatch(BaseModel):
    display_name: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = None          # "" clears the stored key
    enabled: bool | None = None
    timeout_s: int | None = Field(None, ge=1, le=600)
    max_retries: int | None = Field(None, ge=0, le=10)
    extra: dict | None = None


def _check(protocol: str | None, base_url: str | None) -> None:
    if protocol is not None and protocol not in PROTOCOLS:
        raise HTTPException(422, f"protocol must be one of {', '.join(PROTOCOLS)}")
    if base_url is not None and not base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "base_url must start with http:// or https://")


def _get(db: Session, pid: str) -> Provider:
    p = db.get(Provider, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "provider not found")
    return p


@router.get("/providers/presets")
def presets(db: Session = Depends(get_db), _=Depends(current_user)):
    row = db.get(Setting, "provider_presets")
    merged = {p["id"]: p for p in DEFAULT_PRESETS}
    for p in (row.value if row and isinstance(row.value, list) else []):
        if isinstance(p, dict) and p.get("id"):
            merged[p["id"]] = {**merged.get(p["id"], {}), **p}
    return {"items": list(merged.values()), "total": len(merged), "editable": True}


@router.put("/providers/presets")
def put_presets(body: dict[str, Any], db: Session = Depends(get_db), _=Depends(current_user)):
    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(422, "items must be a list")
    clean = [{k: v for k, v in i.items() if k in ("id", "name", "protocol", "base_url",
                                                  "requires_key", "local", "note")}
             for i in items if isinstance(i, dict) and i.get("id")]
    row = db.get(Setting, "provider_presets")
    if row:
        row.value = clean
    else:
        db.add(Setting(key="provider_presets", value=clean))
    db.flush()
    return presets(db)


@router.get("/providers")
def list_providers(limit: int = 50, offset: int = 0, db: Session = Depends(get_db),
                   _=Depends(current_user)):
    q = db.query(Provider).filter(Provider.deleted_at.is_(None))
    return {"items": [provider_out(db, p) for p in
                      q.order_by(Provider.created_at).offset(offset).limit(limit)],
            "total": q.count()}


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn, db: Session = Depends(get_db), _=Depends(current_user)):
    _check(body.protocol, body.base_url)
    p = Provider(display_name=body.display_name, protocol=body.protocol,
                 base_url=body.base_url.rstrip("/"), enabled=body.enabled,
                 timeout_s=body.timeout_s, max_retries=body.max_retries, extra=body.extra)
    db.add(p)
    db.flush()
    if body.api_key:
        set_secret(db, _secret_name(p.id), body.api_key)
        p.secret_ref = _secret_name(p.id)
    audit(db, "provider.created", subject_type="provider", subject_id=p.id,
          detail={"protocol": p.protocol, "base_url": p.base_url, "has_secret": bool(body.api_key)})
    return provider_out(db, p)


@router.get("/providers/{pid}")
def get_provider(pid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    return provider_out(db, _get(db, pid))


@router.patch("/providers/{pid}")
def patch_provider(pid: str, body: ProviderPatch, db: Session = Depends(get_db),
                   _=Depends(current_user)):
    p = _get(db, pid)
    data = body.model_dump(exclude_unset=True)
    _check(data.get("protocol"), data.get("base_url"))
    key = data.pop("api_key", None) if "api_key" in data else "__unset__"
    for k, v in data.items():
        if v is None and k != "extra":
            continue
        setattr(p, k, v.rstrip("/") if k == "base_url" else v)
    if key != "__unset__":
        if key:
            set_secret(db, _secret_name(p.id), key)
            p.secret_ref = _secret_name(p.id)
        elif p.secret_ref:
            delete_secret(db, p.secret_ref)
            p.secret_ref = None
    db.flush()
    audit(db, "provider.updated", subject_type="provider", subject_id=p.id,
          detail={"fields": sorted(k for k in body.model_dump(exclude_unset=True))})
    return provider_out(db, p)


@router.delete("/providers/{pid}", status_code=204)
def delete_provider(pid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    p = _get(db, pid)
    p.deleted_at, p.enabled = datetime.now(timezone.utc), False
    if p.secret_ref:
        delete_secret(db, p.secret_ref)
        p.secret_ref = None
    for m in db.query(Model).filter_by(provider_id=p.id):
        m.enabled = False
    audit(db, "provider.deleted", subject_type="provider", subject_id=p.id)


@router.post("/providers/{pid}/test")
async def test_provider(pid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    _get(db, pid)
    r = await deps.make_gateway(db).test_connection(pid)
    return {"ok": r.ok, "latency_ms": r.latency_ms, "detail": r.detail}


@router.post("/providers/{pid}/discover")
async def discover(pid: str, db: Session = Depends(get_db), _=Depends(current_user)):
    p = _get(db, pid)
    try:
        found = await deps.make_gateway(db).list_models(pid)
    except GatewayError as e:
        raise HTTPException(502, scrub(str(e))) from None
    existing = {m.model_id: m for m in db.query(Model).filter_by(provider_id=p.id)}
    for f in found:
        m = existing.get(f["model_id"])
        declared = {k: v for k, v in (f.get("capabilities") or {}).items()}
        if m is None:   # new models: declared chat only; other capabilities stay unset/unverified
            m = Model(provider_id=p.id, model_id=f["model_id"],
                      capabilities={"chat": True, "protocol": p.protocol, **declared},
                      verified=False, enabled=True)
            db.add(m)
            existing[f["model_id"]] = m
        elif not m.verified:
            m.capabilities = {**(m.capabilities or {}), **declared}
        m.deleted_at = None
    db.flush()
    items = [model_out(m) for m in existing.values()]
    return {"items": items, "total": len(items)}


@router.get("/models")
def list_models(provider_id: str | None = None, limit: int = 200, offset: int = 0,
                db: Session = Depends(get_db), _=Depends(current_user)):
    q = db.query(Model).filter(Model.deleted_at.is_(None))
    if provider_id:
        q = q.filter(Model.provider_id == provider_id)
    return {"items": [model_out(m) for m in q.order_by(Model.created_at).offset(offset).limit(limit)],
            "total": q.count()}


class ModelPatch(BaseModel):
    capabilities: dict | None = None
    enabled: bool | None = None
    verified: bool | None = None


@router.patch("/models/{mid}")
def patch_model(mid: str, body: ModelPatch, db: Session = Depends(get_db),
                _=Depends(current_user)):
    m = db.get(Model, mid)
    if not m or m.deleted_at:
        raise HTTPException(404, "model not found")
    if body.capabilities is not None:
        bad = [k for k, v in body.capabilities.items()
               if k in CAPS and not isinstance(v, bool)]
        if bad:
            raise HTTPException(422, f"capability flags must be booleans: {bad}")
        m.capabilities = {**(m.capabilities or {}), **body.capabilities}
    if body.enabled is not None:
        m.enabled = body.enabled
    if body.verified is not None:
        m.verified = body.verified
    db.flush()
    audit(db, "model.updated", subject_type="model", subject_id=m.id,
          detail=body.model_dump(exclude_unset=True))
    return model_out(m)


@router.get("/usage")
def usage(run_id: str | None = None, from_: str | None = Query(None, alias="from"), to: str | None = None,
          db: Session = Depends(get_db), _=Depends(current_user)):
    """Aggregates over child/agent runs (parents are excluded to avoid double counting)."""
    q = db.query(WorkflowRun)
    if run_id:
        q = q.filter((WorkflowRun.id == run_id) | (WorkflowRun.parent_run_id == run_id))
    for val, op in ((from_, "ge"), (to, "le")):
        if val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(422, "invalid date") from None
            q = q.filter(WorkflowRun.created_at >= dt if op == "ge" else WorkflowRun.created_at <= dt)
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": None,
             "unknown_cost_calls": 0}
    by_agent: dict = {}
    by_model: dict = {}
    parents = {r[0] for r in db.query(WorkflowRun.parent_run_id).filter(
        WorkflowRun.parent_run_id.isnot(None)).distinct()}
    for r in q.all():
        u = r.usage or {}
        if not u or (r.id in parents and not run_id):
            continue
        if run_id and r.id in parents and r.id != run_id:
            continue
        if run_id and r.id == run_id and r.id in parents:
            continue    # parent aggregate: children already counted
        for k in ("calls", "prompt_tokens", "completion_tokens", "unknown_cost_calls"):
            total[k] += u.get(k) or 0
        if u.get("cost_usd") is not None:
            total["cost_usd"] = round((total["cost_usd"] or 0.0) + u["cost_usd"], 8)
        a = by_agent.setdefault(r.agent or "-", {"calls": 0, "cost_usd": None})
        a["calls"] += u.get("calls") or 0
        if u.get("cost_usd") is not None:
            a["cost_usd"] = round((a["cost_usd"] or 0.0) + u["cost_usd"], 8)
        for mk, mv in (u.get("by_model") or {}).items():
            b = by_model.setdefault(mk, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                         "cost_usd": None})
            for k in ("calls", "prompt_tokens", "completion_tokens"):
                b[k] += mv.get(k) or 0
            if mv.get("cost_usd") is not None:
                b["cost_usd"] = round((b["cost_usd"] or 0.0) + mv["cost_usd"], 8)
    total["total_tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    return {"total": total, "by_agent": by_agent, "by_model": by_model}
