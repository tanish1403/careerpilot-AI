import io
import json
import zipfile

import pytest

from careerpilot.core.config import get_settings


@pytest.fixture()
def authed(client):
    s = get_settings()
    s.auth_disabled_for_tests = False
    yield client
    s.auth_disabled_for_tests = True


def _setup(c, pw="correct-horse"):
    r = c.post("/api/v1/auth/setup", json={"username": "alice", "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_auth_flow(authed):
    c = authed
    assert c.get("/api/v1/auth/status").json() == {"setup_required": True}
    assert c.post("/api/v1/auth/setup", json={"username": "a", "password": "short"}).status_code == 422
    h = _setup(c)
    assert c.post("/api/v1/auth/setup", json={"username": "b", "password": "password123"}).status_code == 409
    assert c.get("/api/v1/auth/me", headers=h).json()["username"] == "alice"
    assert c.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    r = c.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert r.status_code == 200 and r.json()["token"]
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token"}).status_code == 401
    assert c.get("/api/v1/settings").status_code == 401


def test_token_expiry(authed, monkeypatch):
    from careerpilot.core import auth
    h = _setup(authed)
    real = auth.time.time()
    monkeypatch.setattr(auth.time, "time", lambda: real + 8 * 24 * 3600)
    assert authed.get("/api/v1/auth/me", headers=h).status_code == 401


def test_settings_roundtrip(client):
    assert client.put("/api/v1/settings/theme", json={"value": {"mode": "dark"}}).status_code == 200
    assert client.get("/api/v1/settings").json()["theme"] == {"mode": "dark"}
    assert client.put("/api/v1/settings/openai_api_key", json={"value": "x"}).status_code == 422


def test_diagnostics_and_logs(client):
    client.put("/api/v1/settings/a", json={"value": 1})
    d = client.get("/api/v1/system/diagnostics").json()
    assert d["db"]["ok"] and set(d["tools"]) == {"xelatex", "tesseract", "playwright", "ollama"}
    assert "running" in d["scheduler"] and d["disk_free_bytes"] > 0
    items = client.get("/api/v1/system/logs?limit=5").json()["items"]
    assert items and items[0]["action"] == "settings.update"
    assert "items" in client.get("/api/v1/system/events").json()


def test_backup_restore_roundtrip(client):
    s = get_settings()
    client.put("/api/v1/settings/keep", json={"value": "before"})
    (s.uploads_dir / "doc.txt").write_text("original")
    b = client.post("/api/v1/system/backup").json()
    assert b["size_bytes"] > 0
    assert b["filename"] in [x["filename"] for x in client.get("/api/v1/system/backups").json()["items"]]
    dl = client.get(f"/api/v1/system/backups/{b['filename']}")
    assert dl.status_code == 200 and zipfile.is_zipfile(io.BytesIO(dl.content))

    client.put("/api/v1/settings/keep", json={"value": "after"})
    client.put("/api/v1/settings/extra", json={"value": 1})
    (s.uploads_dir / "doc.txt").write_text("changed")

    r = client.post("/api/v1/system/restore", json={"filename": b["filename"]})
    assert r.status_code == 200, r.text
    assert r.json()["pre_restore_backup"].startswith("pre-restore")
    st = client.get("/api/v1/settings").json()
    assert st["keep"] == "before" and "extra" not in st
    assert (s.uploads_dir / "doc.txt").read_text() == "original"


def test_restore_validation(client):
    s = get_settings()
    assert client.post("/api/v1/system/restore", json={"filename": "../x.zip"}).status_code == 422
    assert client.post("/api/v1/system/restore", json={"filename": "nope.zip"}).status_code == 404
    (s.backups_dir / "bad.zip").write_bytes(b"not a zip")
    assert client.post("/api/v1/system/restore", json={"filename": "bad.zip"}).status_code == 422
    assert client.get("/api/v1/system/backups/..%2Fsecret.key").status_code in (400, 404)


def test_export_excludes_secrets(client, db):
    from careerpilot.core.secrets import set_secret
    from careerpilot.db.models import User
    db.add(User(username="bob", password_hash="HASH-SENTINEL"))
    set_secret(db, "prov", "sk-supersecretvalue123")
    db.commit()
    r = client.get("/api/v1/system/export")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "secrets.json" not in names and "manifest.json" in names
    blob = b"".join(z.read(n) for n in names)
    assert b"HASH-SENTINEL" not in blob and b"supersecretvalue" not in blob
    from cryptography.fernet import Fernet  # ciphertext must be absent too
    assert b"gAAAA" not in blob
    assert "users" in json.loads(z.read("manifest.json"))["tables"]


def test_wipe_requires_confirm(client):
    client.put("/api/v1/settings/zz", json={"value": 1})
    assert client.request("DELETE", "/api/v1/system/data", json={"confirm": "no"}).status_code == 422
    assert client.request("DELETE", "/api/v1/system/data", json={"confirm": "DELETE"}).status_code == 200
    assert "zz" not in client.get("/api/v1/settings").json()


def test_startup_hook_registered():
    from careerpilot.api import app as app_module
    from careerpilot.core.system.bootstrap import startup
    assert startup in app_module.STARTUP_HOOKS
