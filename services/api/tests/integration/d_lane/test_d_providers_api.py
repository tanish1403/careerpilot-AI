import json
import logging

import httpx

from careerpilot.provider_gateway import deps
from careerpilot.core.audit import audit  # noqa: F401
from careerpilot.db.models import AuditEvent, Secret
from tests.d_support import KEY, Sleeps


def test_provider_crud_key_is_write_only(client, db, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post("/api/v1/providers", json={
        "display_name": "X", "protocol": "openai_compatible",
        "base_url": "https://api.example.com/v1", "api_key": KEY})
    assert r.status_code == 201 and r.json()["has_secret"] is True
    pid = r.json()["id"]
    blobs = [r.text, client.get("/api/v1/providers").text, client.get(f"/api/v1/providers/{pid}").text]
    p = client.patch(f"/api/v1/providers/{pid}", json={"display_name": "Y", "api_key": KEY + "2"})
    blobs.append(p.text)
    db.expire_all()
    blobs += [json.dumps(a.detail) for a in db.query(AuditEvent).all()]
    assert all("SUPERSECRET" not in b for b in blobs) and "SUPERSECRET" not in caplog.text
    assert "SUPERSECRET" not in db.query(Secret).one().ciphertext
    assert client.patch(f"/api/v1/providers/{pid}", json={"api_key": ""}).json()["has_secret"] is False
    assert client.delete(f"/api/v1/providers/{pid}").status_code == 204


def test_presets_test_discover_models_usage(client, db):
    pre = client.get("/api/v1/providers/presets").json()["items"]
    assert {"OmniRoute", "OpenRouter", "FreeLLMAPI", "Ollama", "Anthropic", "OpenAI", "Groq"} <= \
        {p["name"] for p in pre}

    def h(req: httpx.Request):
        if req.url.path.endswith("/models"):
            assert req.headers["authorization"] == f"Bearer {KEY}"
            return httpx.Response(200, json={"data": [{"id": "a", "supported_parameters": ["tools"]},
                                                      {"id": "b"}]})
        return httpx.Response(500, text=f"leak {KEY}")
    deps.transport, deps.sleep = httpx.MockTransport(h), Sleeps()
    try:
        pid = client.post("/api/v1/providers", json={
            "display_name": "X", "protocol": "openai_compatible",
            "base_url": "https://api.example.com/v1", "api_key": KEY}).json()["id"]
        t = client.post(f"/api/v1/providers/{pid}/test").json()
        assert t["ok"] is True and "latency_ms" in t
        d = client.post(f"/api/v1/providers/{pid}/discover")
        assert d.status_code == 200
        ms = client.get(f"/api/v1/models?provider_id={pid}").json()["items"]
        assert {m["model_id"] for m in ms} == {"a", "b"}
        a = next(m for m in ms if m["model_id"] == "a")
        assert a["capabilities"]["tool_calling"] is True and a["verified"] is False
        up = client.patch(f"/api/v1/models/{a['id']}",
                          json={"capabilities": {"structured_output": True}, "enabled": False})
        assert up.json()["capabilities"]["structured_output"] is True and up.json()["enabled"] is False
        assert "total" in client.get("/api/v1/usage").json()
    finally:
        deps.transport = deps.sleep = None


def test_failing_test_endpoint_never_leaks_key(client):
    deps.transport = httpx.MockTransport(lambda r: httpx.Response(500, text=f"echo {KEY}"))
    deps.sleep = Sleeps()
    try:
        pid = client.post("/api/v1/providers", json={
            "display_name": "X", "protocol": "openai_compatible",
            "base_url": "https://api.example.com/v1", "api_key": KEY}).json()["id"]
        r = client.post(f"/api/v1/providers/{pid}/test")
        assert KEY not in r.text and r.json()["ok"] is False
        assert KEY not in client.post(f"/api/v1/providers/{pid}/discover").text
    finally:
        deps.transport = deps.sleep = None


def test_lane_b_hooks_behind_consent_gate(db, client):
    from careerpilot.documents import ingest
    from careerpilot.provider_gateway import hooks
    from careerpilot.resume_engine import service
    from tests.d_support import mk_model, mk_provider, oai_reply, setting
    hooks.install()
    assert ingest.LLM_CALLABLE is not None and service.REWORD_FN is not None
    p = mk_provider(db, url="https://api.example.com/v1")
    mk_model(db, p)
    setting(db, "allow_external_llm", False)
    db.commit()
    calls = []
    deps.transport = httpx.MockTransport(lambda r: calls.append(1) or oai_reply("Built APIs"))
    deps.sleep = Sleeps()
    try:
        assert service.REWORD_FN("Built APIs", "<UNTRUSTED_DATA>jd</UNTRUSTED_DATA>") is None
        try:
            ingest.LLM_CALLABLE("prompt")
            raise AssertionError("expected refusal")
        except RuntimeError:
            pass
        assert calls == []                                 # nothing left the machine
        db.expire_all()
        assert db.query(AuditEvent).filter_by(action="llm.consent_refused").count() == 2
        setting(db, "allow_external_llm", True)
        db.commit()
        assert service.REWORD_FN("Built APIs", "jd") == "Built APIs" and calls
    finally:
        deps.transport = deps.sleep = None
