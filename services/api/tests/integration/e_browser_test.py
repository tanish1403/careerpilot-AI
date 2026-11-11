"""Browser automation tests against local fixture forms (127.0.0.1)."""
import pytest

from e_support import FixtureServer, make_app, make_profile, make_resume

pw = pytest.importorskip("playwright.sync_api")


def _browser_ok() -> str | None:
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return None
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:200]}"


_WHY = _browser_ok()
pytestmark = pytest.mark.skipif(_WHY is not None, reason=f"Playwright chromium unavailable: {_WHY}")


@pytest.fixture()
def srv():
    from careerpilot.browser_automation.session import MANAGER
    with FixtureServer() as s:
        yield s
    MANAGER.shutdown_all()


@pytest.fixture()
def allowed(client, srv):
    r = client.put("/api/v1/automation/allowlist", json={"domains": ["127.0.0.1", "jobs.lever.co"]})
    assert r.status_code == 200
    return srv


def _setup(db, srv, path, key="k", pdf=None):
    app, job = make_app(db, "Approved", url=srv.url(path), key=key)
    p, _ = make_profile(db)
    rv = make_resume(db, p, job, pdf_path=pdf)
    app.resume_version_id = rv.id
    db.commit()
    return app


def _session(client, app):
    r = client.post("/api/v1/automation/sessions", json={"application_id": app.id})
    assert r.status_code == 201, r.text
    return r.json()


def _values(sess_id):
    from careerpilot.browser_automation.session import MANAGER
    s = MANAGER.get(sess_id)
    return s.worker.call(lambda page: page.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('input,select,textarea'))"
        ".filter(e => e.id).map(e => [e.id, e.type === 'checkbox' ? e.checked : e.value]))"))


def test_preview_statuses(client, db, allowed):
    app = _setup(db, allowed, "/greenhouse")
    s = _session(client, app)
    assert s["blockers"] == [] and s["status"] == "open"
    pv = client.post(f"/api/v1/automation/sessions/{s['id']}/fill-preview").json()
    by = {f["label"]: f for f in pv["fields"]}
    for lab, val in (("First Name", "Ada"), ("Last Name", "Lovelace"), ("Email", "ada@example.com"),
                     ("LinkedIn Profile", "https://linkedin.com/in/ada")):
        assert by[lab]["status"] == "ok" and by[lab]["proposed_value"] == val and by[lab]["source"], lab
    assert by["Phone"]["status"] == "ok"
    assert by["Why do you want to work here?"]["status"] == "needs_user"
    for lab in ("Are you legally authorized to work in the United States?", "Gender",
                "I agree to the privacy policy"):
        assert by[lab]["status"] == "sensitive" and by[lab]["proposed_value"] is None, lab
    assert by["Resume/CV"]["status"] == "needs_user"        # no compiled PDF
    assert not any("hp" == f["label"] for f in pv["fields"])  # honeypot excluded
    assert allowed.posts == []


def test_autofill_fills_only_ok_validates_and_never_submits(client, db, allowed, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    app = _setup(db, allowed, "/greenhouse", pdf=str(pdf))
    s = _session(client, app)
    r = client.post(f"/api/v1/automation/sessions/{s['id']}/autofill")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "review" and out["state"] == "UserSubmissionReview"
    rows = {f["label"]: f for f in out["fields"]}
    for lab in ("First Name", "Last Name", "Email", "Phone", "LinkedIn Profile", "Resume/CV"):
        assert rows[lab]["filled"] and rows[lab]["validated"], lab
    assert rows["First Name"]["located_via"] in ("label", "role")        # labels before css
    for lab in ("Gender", "I agree to the privacy policy", "Why do you want to work here?"):
        assert not rows[lab]["filled"], lab
    vals = _values(s["id"])
    assert vals["first_name"] == "Ada" and vals["email"] == "ada@example.com"
    assert vals["gender"] == "" and vals["auth"] == "" and vals["why"] == "" and vals["consent"] is False
    assert vals["resume"].endswith("resume.pdf")
    # needs_user blockers are surfaced for the user to complete
    assert any(b["detail"] == "Why do you want to work here?" for b in out["blockers"])
    # review artifacts
    shot = client.get(f"/api/v1/automation/sessions/{s['id']}/screenshot")
    assert shot.status_code == 200 and shot.content[:4] == b"\x89PNG"
    assert out["review"]["total"] == len(out["fields"])
    # the fixture server NEVER received a POST: nothing submitted
    assert allowed.posts == []
    d = client.get(f"/api/v1/applications/{app.id}").json()
    assert d["state"] == "UserSubmissionReview"
    kinds = [e["kind"] for e in d["events"]]
    assert "autofill_completed" in kinds and "automation_session_started" in kinds
    # field values are not stored in events
    assert "ada@example.com" not in str(d["events"])
    # stop closes the session
    assert client.post(f"/api/v1/automation/sessions/{s['id']}/stop").json()["status"] == "stopped"
    assert client.post(f"/api/v1/automation/sessions/{s['id']}/autofill").status_code == 409


def test_post_requests_are_blocked_by_guard(client, db, allowed):
    app = _setup(db, allowed, "/greenhouse")
    s = _session(client, app)
    from careerpilot.browser_automation.session import MANAGER
    sess = MANAGER.get(s["id"])
    res = sess.worker.call(lambda page: page.evaluate(
        "() => fetch('/submit', {method: 'POST', body: 'x'}).then(() => 'sent').catch(() => 'blocked')"))
    assert res == "blocked" and allowed.posts == [] and sess.worker.blocked_methods >= 1


@pytest.mark.parametrize("path,kind", [("/captcha", "captcha"), ("/login", "login_required"),
                                       ("/ambiguous", "ambiguous_form")])
def test_hard_blockers_stop_autofill(client, db, allowed, path, kind):
    app = _setup(db, allowed, path)
    s = _session(client, app)
    r = client.post(f"/api/v1/automation/sessions/{s['id']}/autofill")
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "blocked" and out["state"] == "Blocked"
    assert kind in [b["kind"] for b in out["blockers"]]
    assert out["fields"] == []
    d = client.get(f"/api/v1/applications/{app.id}").json()
    assert d["state"] == "Blocked" and any(b["kind"] == kind for b in d["blockers"])
    assert [e for e in d["events"] if e["kind"] == "automation_blocked"]
    assert allowed.posts == []


def test_preview_reports_captcha_without_state_change(client, db, allowed):
    app = _setup(db, allowed, "/captcha")
    s = _session(client, app)
    assert "captcha" in [b["kind"] for b in s["blockers"]]
    pv = client.post(f"/api/v1/automation/sessions/{s['id']}/fill-preview").json()
    assert pv["fields"] == [] and pv["blockers"][0]["kind"] == "captcha"
    assert client.get(f"/api/v1/applications/{app.id}").json()["state"] == "Approved"


def test_redirect_off_allowlist_is_blocked(client, db, allowed):
    app = _setup(db, allowed, "/redirect")
    s = _session(client, app)
    assert "domain_not_allowed" in [b["kind"] for b in s["blockers"]]
    assert ("GET", "/greenhouse") not in allowed.httpd.log          # the off-list hop never happened
    r = client.post(f"/api/v1/automation/sessions/{s['id']}/autofill").json()
    assert r["status"] == "blocked"
    assert client.get(f"/api/v1/applications/{app.id}").json()["state"] == "Blocked"
    assert allowed.posts == []


def test_sensitive_form_leaves_sensitive_fields_for_user(client, db, allowed):
    app = _setup(db, allowed, "/sensitive")
    s = _session(client, app)
    pv = client.post(f"/api/v1/automation/sessions/{s['id']}/fill-preview").json()
    st = {f["label"]: f["status"] for f in pv["fields"]}
    assert st["Will you now or in the future require visa sponsorship?"] == "sensitive"
    assert st["Do you have a disability?"] == "sensitive"
    assert st["Have you ever been convicted of a felony?"] == "sensitive"
    # even a user-confirmed answer to a sensitive question is not auto-filled
    out = client.post(f"/api/v1/automation/sessions/{s['id']}/autofill").json()
    vals = _values(s["id"])
    assert vals["vis"] == "" and vals["dis"] == "" and vals["crim"] == ""
    assert vals["first_name"] == "Ada" and out["status"] == "review"
    assert {b["detail"] for b in out["blockers"]} >= {"Do you have a disability?"}
    assert allowed.posts == []


def test_readback_validation_catches_rejecting_field(client, db, allowed):
    app = _setup(db, allowed, "/reject")
    s = _session(client, app)
    out = client.post(f"/api/v1/automation/sessions/{s['id']}/autofill").json()
    rows = {f["label"]: f for f in out["fields"]}
    assert rows["First Name"]["validated"] is True
    assert rows["Email"]["filled"] is False and rows["Email"]["validated"] is False
    assert rows["Email"]["fill_status"] == "mismatch"
    assert "Email" in out["review"]["validation_failures"]
    assert any(b["detail"] == "Email" and b["status"] == "validation_failed" for b in out["blockers"])
    assert allowed.posts == []


def test_adapter_detect_and_direct_extract(client, db, allowed):
    from careerpilot.browser_automation.adapters import (AshbyAdapter, GreenhouseAdapter, LeverAdapter,
                                                         get_adapter)
    assert GreenhouseAdapter().detect("https://job-boards.greenhouse.io/a/jobs/1")
    assert LeverAdapter().detect("https://jobs.lever.co/a/b/apply")
    assert AshbyAdapter().detect("https://jobs.ashbyhq.com/a/b/application")
    assert get_adapter("https://jobs.lever.co/x").name == "lever"
    assert get_adapter("http://127.0.0.1/x").name == "generic"
    app = _setup(db, allowed, "/greenhouse")
    s = _session(client, app)
    from careerpilot.browser_automation.session import MANAGER
    sess = MANAGER.get(s["id"])
    fields = sess.worker.call(lambda page: GreenhouseAdapter().extract_fields(page))
    labels = [f.label for f in fields]
    assert "First Name" in labels and "hp" not in labels
    assert next(f for f in fields if f.label == "Resume/CV").kind == "file"
    assert next(f for f in fields if f.label == "Gender").options == ["--", "Female", "Male"]


def test_same_host_redirect_is_followed(client, db, allowed):
    app = _setup(db, allowed, "/redirect-ok")
    s = _session(client, app)
    assert s["blockers"] == []
    pv = client.post(f"/api/v1/automation/sessions/{s['id']}/fill-preview").json()
    assert any(f["label"] == "Email" for f in pv["fields"])
