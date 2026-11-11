from careerpilot.core.audit import audit
from careerpilot.core.redaction import redact, redact_text
from careerpilot.core.system.runs import start_run, fail_run


def test_redaction():
    out = redact({"api_key": "sk-abcdefgh12345", "note": "mail me a@b.com sk-abcdefgh12345",
                  "nested": [{"Authorization": "Bearer abcdefghijkl"}]})
    assert out["api_key"] == "[REDACTED]"
    assert "a@b.com" not in out["note"] and "sk-abcdefgh" not in out["note"]
    assert out["nested"][0]["Authorization"] == "[REDACTED]"
    assert "[truncated" in redact_text("x" * 600)


def test_audit_redacts(db):
    ev = audit(db, "t", detail={"password": "hunter2", "ok": 1})
    assert ev.detail == {"password": "[REDACTED]", "ok": 1}


def test_run_idempotency(db):
    a = start_run(db, "matcher", {"x": 1}, idempotency_key="k1")
    b = start_run(db, "matcher", {"x": 1}, idempotency_key="k1")
    assert a.id == b.id
    assert start_run(db, "other", {}, idempotency_key="k1").id != a.id
    fail_run(db, a, "boom")
    c = start_run(db, "matcher", {}, idempotency_key="k1")
    assert c.id != a.id  # failed runs may be retried
