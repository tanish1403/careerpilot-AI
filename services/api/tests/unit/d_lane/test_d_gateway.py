import json
import logging

import httpx
import pytest

from careerpilot.provider_gateway.errors import (BudgetExceeded, ConsentRequired, GatewayError,
                                                 NoRouteError)
from careerpilot.provider_gateway.gateway import Gateway
from careerpilot.provider_gateway.interface import GenerateRequest, TaskPolicy
from careerpilot.db.models import AgentConfig, WorkflowRun
from tests.d_support import (GOOD, KEY, SCHEMA, Sleeps, mk_model, mk_provider, oai_reply, setting,
                             transport)

REQ = GenerateRequest(messages=[{"role": "user", "content": "hi"}])


def gw(db, handler, sleep=None):
    return Gateway(db, transport=transport(handler), sleep=sleep or Sleeps())


async def test_openai_adapter_shape_and_auth(db):
    seen = {}

    def h(r: httpx.Request):
        seen["url"], seen["auth"], seen["body"] = str(r.url), r.headers.get("authorization"), \
            json.loads(r.content)
        return oai_reply("hello")
    p = mk_provider(db, key=KEY)
    mk_model(db, p)
    res = await gw(db, h).generate(REQ, TaskPolicy(task_type="t"))
    assert res.text == "hello" and res.usage["prompt_tokens"] == 10
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}" and seen["body"]["model"] == "m1"
    assert res.usage["cost_usd"] is None   # unknown cost is None, never 0


async def test_ollama_adapter(db):
    def h(r):
        assert r.url.path == "/api/chat"
        body = json.loads(r.content)
        assert body["format"] == SCHEMA
        return httpx.Response(200, json={"message": {"content": GOOD}, "prompt_eval_count": 7,
                                         "eval_count": 3})
    p = mk_provider(db, "ollama", "http://localhost:11434")
    mk_model(db, p)
    res = await gw(db, h).generate(REQ, TaskPolicy(task_type="t", json_schema=SCHEMA))
    assert res.parsed == {"answer": "ok"} and res.usage["completion_tokens"] == 3


async def test_anthropic_adapter(db):
    def h(r):
        assert r.url.path == "/v1/messages" and r.headers["x-api-key"] == KEY
        body = json.loads(r.content)
        assert "system" in body and all(m["role"] != "system" for m in body["messages"])
        return httpx.Response(200, json={"content": [{"type": "text", "text": "yo"}],
                                         "usage": {"input_tokens": 4, "output_tokens": 2}})
    p = mk_provider(db, "anthropic", "https://api.anthropic.com", key=KEY)
    mk_model(db, p)
    req = GenerateRequest(messages=[{"role": "system", "content": "s"},
                                    {"role": "user", "content": "u"}])
    res = await gw(db, h).generate(req, TaskPolicy(task_type="t"))
    assert res.text == "yo" and res.usage["prompt_tokens"] == 4


async def test_capability_routing_ignores_model_names(db):
    called = []

    def h(r):
        called.append(json.loads(r.content)["model"])
        return oai_reply(GOOD)
    p = mk_provider(db)
    mk_model(db, p, "gpt-4o-structured-json")            # name suggests it, caps do not
    mk_model(db, p, "plain-model", structured_output=True)
    res = await gw(db, h).generate(REQ, TaskPolicy(task_type="t", require=["structured_output"],
                                                   json_schema=SCHEMA))
    assert called == ["plain-model"] and res.model_id == "plain-model"
    with pytest.raises(NoRouteError):
        await gw(db, h).generate(REQ, TaskPolicy(task_type="t", require=["vision"]))


async def test_retries_use_injected_sleep(db):
    n = {"c": 0}

    def h(r):
        n["c"] += 1
        return httpx.Response(503, text="busy") if n["c"] < 3 else oai_reply("fine")
    p = mk_provider(db, retries=2)
    mk_model(db, p)
    s = Sleeps()
    res = await gw(db, h, s).generate(REQ, TaskPolicy(task_type="t"))
    assert res.text == "fine" and n["c"] == 3 and len(s.calls) == 2
    assert res.attempts[0]["retries"] == 2 and res.fallback_used is False


async def test_non_retryable_not_retried(db):
    n = {"c": 0}

    def h(r):
        n["c"] += 1
        return httpx.Response(401, text="no")
    p = mk_provider(db, retries=3)
    mk_model(db, p)
    with pytest.raises(GatewayError):
        await gw(db, h).generate(REQ, TaskPolicy(task_type="t"))
    assert n["c"] == 1


async def test_fallback_preserves_structured_contract(db):
    bodies = []

    def h(r):
        b = json.loads(r.content)
        bodies.append(b)
        if r.url.host == "a.example.com":
            return oai_reply("not json at all")
        return oai_reply(GOOD)
    a = mk_provider(db, url="https://a.example.com/v1", name="A")
    b = mk_provider(db, url="https://b.example.com/v1", name="B")
    ma, mb = mk_model(db, a, "ma", structured_output=True), mk_model(db, b, "mb",
                                                                      structured_output=True)
    db.add(AgentConfig(agent="matching", primary_model_id=ma.id, fallback_model_ids=[mb.id]))
    db.flush()
    res = await gw(db, h).generate(REQ, TaskPolicy(task_type="t", agent="matching",
                                                   json_schema=SCHEMA))
    assert res.fallback_used and res.parsed == {"answer": "ok"} and res.model_id == "mb"
    assert [x["ok"] for x in res.attempts] == [False, True]
    # schema instruction was sent to the fallback too
    assert "JSON schema" in bodies[-1]["messages"][0]["content"]


async def test_fallback_output_violating_schema_rejected(db):
    p = mk_provider(db)
    mk_model(db, p)
    with pytest.raises(GatewayError):
        await gw(db, lambda r: oai_reply('{"wrong": 1}')).generate(
            REQ, TaskPolicy(task_type="t", json_schema=SCHEMA))


async def test_secret_never_leaks_in_errors_attempts_or_logs(db, caplog):
    caplog.set_level(logging.DEBUG)

    def h(r):
        return httpx.Response(500, text=f"upstream echo: key={KEY} Authorization: Bearer {KEY}")
    p = mk_provider(db, key=KEY, retries=1)
    mk_model(db, p)
    run = WorkflowRun(agent="matching", status="running")
    db.add(run)
    db.flush()
    with pytest.raises(GatewayError) as ei:
        await gw(db, h).generate(GenerateRequest(messages=REQ.messages, run_id=run.id),
                                 TaskPolicy(task_type="t"))
    blob = str(ei.value) + json.dumps(ei.value.attempts) + caplog.text + json.dumps(
        run.provider_meta)
    assert KEY not in blob and "SUPERSECRET" not in blob
    health = await gw(db, h).health(p.id)
    assert KEY not in (health.detail or "")
    with pytest.raises(GatewayError) as ei2:
        await gw(db, h).list_models(p.id)
    assert KEY not in str(ei2.value)


async def test_consent_gate(db):
    p = mk_provider(db, url="https://api.example.com/v1")
    mk_model(db, p)
    pol = TaskPolicy(task_type="t", sensitive_document=True)
    g = gw(db, lambda r: oai_reply("x"))
    with pytest.raises(ConsentRequired):
        await g.generate(REQ, pol)
    setting(db, "allow_external_llm", False)
    with pytest.raises(ConsentRequired):
        await g.generate(REQ, pol)
    setting(db, "allow_external_llm", True)
    assert (await g.generate(REQ, pol)).text == "x"


async def test_consent_gate_allows_local_and_skips_external(db):
    ext = mk_provider(db, url="https://api.example.com/v1", name="ext")
    mk_model(db, ext, "ext-m")
    loc = mk_provider(db, "ollama", "http://localhost:11434", name="loc")
    mk_model(db, loc, "loc-m")
    seen = []

    def h(r):
        seen.append(r.url.host)
        return httpx.Response(200, json={"message": {"content": "local"}})
    res = await gw(db, h).generate(REQ, TaskPolicy(task_type="t", sensitive_document=True))
    assert res.text == "local" and seen == ["localhost"]
    with pytest.raises(NoRouteError):
        await gw(db, h).generate(REQ, TaskPolicy(task_type="t", local_only=True,
                                                 require=["vision"]))


async def test_cost_tracking_and_budgets(db):
    p = mk_provider(db)
    mk_model(db, p, "priced")
    setting(db, "pricing", {"priced": {"prompt_per_1k": 1.0, "completion_per_1k": 2.0}})
    run = WorkflowRun(agent="matching", status="running")
    db.add(run)
    db.add(AgentConfig(agent="matching", budget_usd=0.05))
    db.flush()
    g = gw(db, lambda r: oai_reply("x", pt=1000, ct=500))
    req = GenerateRequest(messages=REQ.messages, run_id=run.id, max_tokens=10)
    pol = TaskPolicy(task_type="t", agent="matching")
    res = await g.generate(req, pol)
    assert res.usage["cost_usd"] == pytest.approx(2.0)
    assert g.usage(run.id)["cost_usd"] == pytest.approx(2.0)
    with pytest.raises(BudgetExceeded):    # agent budget 0.05 already blown
        await g.generate(req, pol)


async def test_run_budget_setting(db):
    p = mk_provider(db)
    mk_model(db, p)
    setting(db, "run_budget_usd", 0.001)
    setting(db, "pricing", {"m1": {"prompt_per_1k": 1.0, "completion_per_1k": 1.0}})
    run = WorkflowRun(agent="x", status="running")
    db.add(run)
    db.flush()
    with pytest.raises(BudgetExceeded):
        await gw(db, lambda r: oai_reply("x")).generate(
            GenerateRequest(messages=[{"role": "user", "content": "y" * 4000}], run_id=run.id),
            TaskPolicy(task_type="t"))
