import pytest
from careerpilot.applications import service as svc
from careerpilot.db.models import Application, Approval, ApplicationEvent

from e_support import make_app, make_job, make_profile, make_resume


def _ready_for_submit(db, client):
    """Application in UserSubmissionReview with approved resume and resolved answers."""
    app, job = make_app(db, "ReviewRequired")
    p, _ = make_profile(db)
    rv = make_resume(db, p, job)
    db.commit()
    r = client.post(f"/api/v1/applications/{app.id}/approve-resume", json={"resume_version_id": rv.id})
    assert r.status_code == 200 and r.json()["state"] == "Approved"
    for to in ("AutofillInProgress", "UserSubmissionReview"):
        assert client.post(f"/api/v1/applications/{app.id}/transition", json={"to_state": to}).status_code == 200
    return app, rv


def test_create_idempotent_per_job(client, db):
    job = make_job(db)
    db.commit()
    a = client.post("/api/v1/applications", json={"job_id": job.id})
    b = client.post("/api/v1/applications", json={"job_id": job.id})
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"] and b.json()["created"] is False
    assert db.query(Application).count() == 1
    assert client.post("/api/v1/applications", json={"job_id": "nope"}).status_code == 404


def test_idempotency_key_other_job_conflict(client, db):
    j1, j2 = make_job(db, key="a"), make_job(db, key="b")
    db.commit()
    assert client.post("/api/v1/applications", json={"job_id": j1.id, "idempotency_key": "K"}).status_code == 201
    assert client.post("/api/v1/applications", json={"job_id": j2.id, "idempotency_key": "K"}).status_code == 409


def test_transition_route_and_kanban_detail(client, db):
    app, _ = make_app(db)
    r = client.post(f"/api/v1/applications/{app.id}/transition", json={"to_state": "Analyzed"})
    assert r.status_code == 200 and r.json()["state"] == "Analyzed"
    assert set(r.json()["allowed_transitions"]) == {"Shortlisted", "Rejected"}
    assert client.post(f"/api/v1/applications/{app.id}/transition", json={"to_state": "Offer"}).status_code == 409
    k = client.get("/api/v1/applications/kanban").json()
    col = {c["state"]: c["items"] for c in k["columns"]}
    assert len(col["Analyzed"]) == 1 and "Submitted" in col
    d = client.get(f"/api/v1/applications/{app.id}").json()
    assert {"job", "resume_version", "answers", "events", "allowed_transitions", "blockers"} <= d.keys()
    assert [e["kind"] for e in d["events"]][:2] == ["created", "transition"]
    assert client.get("/api/v1/applications?state=Analyzed").json()[0]["id"] == app.id


def test_submitted_unreachable_via_generic_endpoint(client, db):
    app, _ = make_app(db, "UserSubmissionReview")
    r = client.post(f"/api/v1/applications/{app.id}/transition", json={"to_state": "Submitted"})
    assert r.status_code == 409
    app2, _ = make_app(db, "ReviewRequired", key="k2")
    assert client.post(f"/api/v1/applications/{app2.id}/transition", json={"to_state": "Approved"}).status_code == 409
    db.expire_all()
    assert db.get(Application, app.id).state == "UserSubmissionReview"


def test_submit_unreachable_without_granted_approval(client, db):
    app, _ = _ready_for_submit(db, client)
    # no approval at all
    assert client.post(f"/api/v1/applications/{app.id}/confirm-submitted",
                       json={"approval_id": "x"}).status_code == 409
    ap = client.post(f"/api/v1/applications/{app.id}/request-submit")
    assert ap.status_code == 201 and ap.json()["status"] == "pending"
    snap = ap.json()["snapshot"]
    assert snap["resume_version_id"] and snap["destination_url"] and snap["requested_at"]
    # pending (not granted) approval is not enough
    assert client.post(f"/api/v1/applications/{app.id}/confirm-submitted",
                       json={"approval_id": ap.json()["id"]}).status_code == 409
    # another application's approval is not enough
    other, _ = make_app(db, "UserSubmissionReview", key="o")
    assert client.post(f"/api/v1/applications/{other.id}/confirm-submitted",
                       json={"approval_id": ap.json()["id"]}).status_code == 409
    db.expire_all()
    assert db.get(Application, app.id).state == "UserSubmissionReview"


def test_full_happy_path_and_duplicate_refused(client, db):
    app, rv = _ready_for_submit(db, client)
    ap = client.post(f"/api/v1/applications/{app.id}/request-submit").json()
    again = client.post(f"/api/v1/applications/{app.id}/request-submit").json()
    assert again["id"] == ap["id"]                                  # idempotent request
    g = client.post(f"/api/v1/applications/{app.id}/grant-submit", json={"approval_id": ap["id"]})
    assert g.json()["status"] == "granted"
    r = client.post(f"/api/v1/applications/{app.id}/confirm-submitted",
                    json={"approval_id": ap["id"], "confirmation_ref": "CONF-123"})
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "Submitted" and d["confirmation_ref"] == "CONF-123"
    assert d["submitted_at"] and d["follow_up_at"] and d["submission_approval_id"] == ap["id"]
    # duplicate submission refused
    r2 = client.post(f"/api/v1/applications/{app.id}/confirm-submitted", json={"approval_id": ap["id"]})
    assert r2.status_code == 409
    assert client.post(f"/api/v1/applications/{app.id}/request-submit").status_code == 409
    # still exactly one application for the job; creating again returns the same
    assert client.post("/api/v1/applications", json={"job_id": d["job_id"]}).json()["id"] == app.id


def test_approval_invalidated_after_answer_edit(client, db):
    app, _ = _ready_for_submit(db, client)
    ap = client.post(f"/api/v1/applications/{app.id}/request-submit").json()
    client.post(f"/api/v1/applications/{app.id}/grant-submit", json={"approval_id": ap["id"]})
    r = client.put(f"/api/v1/applications/{app.id}/answers",
                   json={"answers": [{"question": "Why us?", "answer": "Because"}]})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Approval, ap["id"]).status == "expired"
    assert db.query(ApplicationEvent).filter_by(kind="approval_invalidated").count() >= 1
    assert client.post(f"/api/v1/applications/{app.id}/confirm-submitted",
                       json={"approval_id": ap["id"]}).status_code == 409
    assert db.get(Application, app.id).state == "UserSubmissionReview"


def test_snapshot_mismatch_blocks_confirm_even_if_tampered(client, db):
    app, _ = _ready_for_submit(db, client)
    ap = client.post(f"/api/v1/applications/{app.id}/request-submit").json()
    client.post(f"/api/v1/applications/{app.id}/grant-submit", json={"approval_id": ap["id"]})
    # change destination behind the service's back (no invalidation hook)
    row = db.get(Application, app.id)
    row.destination_url = "https://jobs.lever.co/other/1"
    db.commit()
    r = client.post(f"/api/v1/applications/{app.id}/confirm-submitted", json={"approval_id": ap["id"]})
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Approval, ap["id"]).status == "expired"      # invalidation persisted despite 409
    assert db.get(Application, app.id).state == "UserSubmissionReview"


def test_request_submit_requires_review_state_resume_and_resolved_answers(client, db):
    a, _ = make_app(db, "Approved", key="a0")
    assert client.post(f"/api/v1/applications/{a.id}/request-submit").status_code == 409
    b, _ = make_app(db, "UserSubmissionReview", key="b")          # no resume approved
    assert client.post(f"/api/v1/applications/{b.id}/request-submit").status_code == 409
    c, _ = _ready_for_submit(db, client)
    client.put(f"/api/v1/applications/{c.id}/answers", json={"answers": [{"question": "Visa sponsorship?"}]})
    r = client.post(f"/api/v1/applications/{c.id}/request-submit")
    assert r.status_code == 409 and "answer" in r.json()["detail"]


def test_approve_resume_rules(client, db):
    app, job = make_app(db, "Shortlisted")
    p, _ = make_profile(db)
    rv = make_resume(db, p, job)
    other = make_job(db, key="zz")
    rv_other = make_resume(db, p, other)
    db.commit()
    assert client.post(f"/api/v1/applications/{app.id}/approve-resume",
                       json={"resume_version_id": rv.id}).status_code == 409   # wrong state
    app.state = "ReviewRequired"
    db.commit()
    assert client.post(f"/api/v1/applications/{app.id}/approve-resume",
                       json={"resume_version_id": rv_other.id}).status_code == 409
    assert client.post(f"/api/v1/applications/{app.id}/approve-resume",
                       json={"resume_version_id": "nope"}).status_code == 404
    r = client.post(f"/api/v1/applications/{app.id}/approve-resume", json={"resume_version_id": rv.id})
    d = r.json()
    assert d["state"] == "Approved" and d["resume_version_id"] == rv.id and d["approved_by"] and d["approved_at"]
    assert d["approval"]["status"] == "granted"
    ap = db.query(Approval).filter_by(kind="resume", subject_id=app.id).one()
    assert ap.snapshot["resume_version_id"] == rv.id


def test_prepare_drafts_only_from_confirmed_facts(client, db):
    app, job = make_app(db, "Shortlisted")
    p, _ = make_profile(db, confirmed=True)
    make_resume(db, p, job)
    db.commit()
    r = client.post(f"/api/v1/applications/{app.id}/prepare",
                    json={"questions": ["Do you have a disability?", "Why do you want this job?"]})
    assert r.status_code == 202
    ans = {a["question"]: a for a in client.get(f"/api/v1/applications/{app.id}/answers").json()}
    assert ans["Email"]["answer"] == "ada@example.com" and ans["Email"]["evidence_ids"]
    assert ans["Full name"]["answer"] == "Ada Lovelace" and not ans["Full name"]["needs_user"]
    assert ans["Current company"]["answer"] == "Analytical Engines"
    for q in ("Do you have a disability?", "Why do you want this job?"):
        assert ans[q]["answer"] is None and ans[q]["needs_user"] and ans[q]["evidence_ids"] == []
    assert ans["Do you have a disability?"]["sensitive"] is True
    assert client.get(f"/api/v1/applications/{app.id}").json()["state"] == "ReviewRequired"


def test_unconfirmed_facts_are_never_used(client, db):
    app, _ = make_app(db, "Shortlisted")
    make_profile(db, confirmed=False)
    db.commit()
    client.post(f"/api/v1/applications/{app.id}/prepare")
    ans = client.get(f"/api/v1/applications/{app.id}/answers").json()
    assert ans and all(a["answer"] is None and a["needs_user"] for a in ans)


def test_user_edit_and_confirm_answer(client, db):
    app, _ = make_app(db, "Shortlisted")
    make_profile(db)
    db.commit()
    client.post(f"/api/v1/applications/{app.id}/prepare")
    ans = client.get(f"/api/v1/applications/{app.id}/answers").json()
    email = next(a for a in ans if a["question"] == "Email")
    r = client.put(f"/api/v1/applications/{app.id}/answers",
                   json={"answers": [{"id": email["id"], "answer": "ada@work.example"}]})
    e = next(a for a in r.json() if a["id"] == email["id"])
    assert e["answer"] == "ada@work.example" and not e["user_confirmed"] and e["evidence_ids"] == []
    c = client.post(f"/api/v1/answers/{email['id']}/confirm").json()
    assert c["user_confirmed"] and not c["needs_user"]
    empty = next(a for a in ans if a["question"] == "GitHub profile")
    assert client.post(f"/api/v1/answers/{empty['id']}/confirm").status_code == 409
    assert client.put(f"/api/v1/applications/{app.id}/answers", json={"answers": [{"id": "zz", "answer": "x"}]}).status_code == 404


def test_follow_up_and_confirmation_ref(client, db):
    app, _ = make_app(db, "Analyzed")
    r = client.patch(f"/api/v1/applications/{app.id}",
                     json={"follow_up_at": "2020-01-01T00:00:00Z", "notes": "ping recruiter"})
    assert r.json()["follow_up_at"] and r.json()["notes"] == "ping recruiter"
    assert client.get("/api/v1/applications/follow-ups").json() == []        # not submitted yet
    assert client.patch(f"/api/v1/applications/{app.id}", json={"confirmation_ref": "x"}).status_code == 409
    app.state = "Submitted"
    db.commit()
    assert [a["id"] for a in client.get("/api/v1/applications/follow-ups").json()] == [app.id]
    assert client.patch(f"/api/v1/applications/{app.id}", json={"confirmation_ref": "REF9"}).json()["confirmation_ref"] == "REF9"


def test_allowlist_and_adapter_routes(client):
    assert "jobs.lever.co" in client.get("/api/v1/automation/allowlist").json()["domains"]
    assert client.put("/api/v1/automation/allowlist", json={"domains": ["*.evil.com"]}).status_code == 422
    r = client.put("/api/v1/automation/allowlist", json={"domains": ["jobs.lever.co", "127.0.0.1"]})
    assert r.json()["domains"] == ["127.0.0.1", "jobs.lever.co"]
    names = {a["name"] for a in client.get("/api/v1/automation/adapters").json()}
    assert {"greenhouse", "lever", "ashby", "generic"} <= names


def test_session_requires_state_and_allowlisted_domain(client, db):
    a, _ = make_app(db, "ReviewRequired")
    assert client.post("/api/v1/automation/sessions", json={"application_id": a.id}).status_code == 409
    b, _ = make_app(db, "Approved", url="https://evil.example.com/apply", key="e")
    r = client.post("/api/v1/automation/sessions", json={"application_id": b.id})
    assert r.status_code == 403
    assert client.post("/api/v1/automation/sessions", json={"application_id": "zz"}).status_code == 404
    assert client.get("/api/v1/automation/sessions/zz").status_code == 404
    d = client.get(f"/api/v1/applications/{b.id}").json()
    assert any(x["kind"] == "domain_not_allowlisted" for x in d["blockers"])
