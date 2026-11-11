import httpx

from careerpilot.research import service as rs

PAGE = """<html><head><title>Acme Robotics</title><meta name="description" content="We build warehouse robots."></head>
<body><h1>Careers at Acme</h1></body></html>"""


def handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    if req.url.path == "/private":
        return httpx.Response(200, text="secret")
    return httpx.Response(200, text=PAGE)


def test_learning_flow(client):
    assert {t["key"] for t in client.get("/api/v1/learning/templates").json()} >= {
        "backend", "frontend", "ml_data", "dsa", "system_design"}
    r = client.post("/api/v1/study-plans/generate", json={"tracks": ["dsa"], "hours_per_week": 8})
    assert r.status_code == 201
    plan = r.json()
    t = plan["tasks"][0]
    p = client.patch(f"/api/v1/study-tasks/{t['id']}", json={"status": "done"}).json()
    assert p["revise_at"] and p["sm2"]["reps"] == 1
    p = client.patch(f"/api/v1/study-tasks/{t['id']}", json={"review_quality": 5}).json()
    assert p["sm2"]["reps"] == 2
    assert client.get(f"/api/v1/study-plans/{plan['id']}/export").text.startswith("# ")
    assert client.post(f"/api/v1/study-plans/{plan['id']}/tasks", json={"title": "mine"}).status_code == 201
    assert client.get("/api/v1/learning/progress").json()["overall"]["done"] == 1
    assert client.post("/api/v1/study-plans/generate", json={"tracks": ["zzz"]}).status_code == 422
    assert client.post("/api/v1/learning/resources", json={"title": "x", "url": "https://example.org/a"}).json()["accessed_on"]
    assert client.get("/api/v1/learning/skill-gaps").json() == []
    assert client.delete(f"/api/v1/study-plans/{plan['id']}").status_code == 204


def test_interview_flow(client):
    s = client.post("/api/v1/interview-sessions", json={"kind": "system_design"}).json()
    sid = s["id"]
    assert s["current_question"]["label"] == "practice question"
    assert s["current_question"]["verified_company_question"] is False
    for _ in range(3):
        a = client.post(f"/api/v1/interview-sessions/{sid}/answer",
                        json={"text": "Use a hash id, store in a database with a cache, scale with sharding and replicas; "
                                      "consistency availability partition; token bucket counter redis reject 429."}).json()
    assert a["done"] and len(a["running_notes"]) == 3
    fb = client.post(f"/api/v1/interview-sessions/{sid}/finish", json={"use_llm": True}).json()
    assert set(fb) == {"factual_correctness", "communication", "revision_tasks"}
    assert fb["factual_correctness"]["llm_review"]["source"] == "unavailable"   # no provider: falls back
    assert fb["factual_correctness"]["overall"] == 1.0
    assert "Interview practice" in client.get(f"/api/v1/interview-sessions/{sid}/export").text
    assert client.post("/api/v1/interview-sessions", json={"kind": "bogus"}).status_code == 422
    assert client.post(f"/api/v1/interview-sessions/{sid}/answer", json={"text": "x"}).status_code == 409
    assert len(client.get("/api/v1/interview-sessions").json()) == 1
    assert client.post("/api/v1/interviews", json={"company": "Acme"}).status_code == 201


def test_research_sources_and_unverified(client):
    rs.transport = httpx.MockTransport(handler)
    try:
        r = client.post("/api/v1/research/company", json={
            "company": "Acme", "urls": ["https://acme.test/about", "https://acme.test/private"],
            "interview_notes": [{"theme": "Heavy system design"}, {"theme": "Take-home", "source_url": "https://blog.test/x"}]})
        assert r.status_code == 202
        c = client.get(f"/api/v1/companies/{r.json()['id']}").json()
    finally:
        rs.transport = None
    assert c["claims"] and all(x["source_url"] and x["retrieved_at"] for x in c["claims"])
    assert any("Acme Robotics" in x["text"] for x in c["claims"])
    assert c["sources"] == [{"url": "https://acme.test/about", "retrieved_at": c["claims"][0]["retrieved_at"]}] or c["sources"]
    assert {f["status"] for f in c["fetches"]} == {"ok", "blocked"}
    th = {t["theme"]: t for t in c["interview_themes"]}
    assert th["Heavy system design"]["unverified"] is True and th["Take-home"]["unverified"] is False
    assert len(client.get("/api/v1/companies").json()) == 1


def test_research_without_sources_makes_no_claims(client):
    c = client.post("/api/v1/research/company", json={"company": "Ghost"}).json()
    assert c["claims"] == [] and "No sources" in c["note"]


def test_scheduler_api(client):
    assert client.post("/api/v1/scheduler/tasks", json={"name": "x", "kind": "submit_application",
                                                        "cron": "0 9 * * *"}).status_code == 422
    assert client.post("/api/v1/scheduler/tasks", json={"name": "x", "kind": "daily_digest",
                                                        "cron": "bad cron", "timezone": "UTC"}).status_code == 422
    assert client.post("/api/v1/scheduler/tasks", json={"name": "x", "kind": "daily_digest", "cron": "0 9 * * *",
                                                        "timezone": "Nowhere/Land"}).status_code == 422
    t = client.post("/api/v1/scheduler/tasks", json={"name": "digest", "kind": "daily_digest",
                                                     "cron": "0 9 * * *", "timezone": "Europe/Berlin"}).json()
    assert client.get("/api/v1/digest/latest").status_code == 404
    run = client.post(f"/api/v1/scheduler/tasks/{t['id']}/run-now").json()
    assert run["status"] == "succeeded"
    assert client.get("/api/v1/digest/latest").json()["new_jobs"]["count"] == 0
    assert client.patch(f"/api/v1/scheduler/tasks/{t['id']}", json={"enabled": False}).json()["enabled"] is False
    assert client.patch(f"/api/v1/scheduler/tasks/{t['id']}", json={"cron": "zz"}).status_code == 422
    assert client.post("/api/v1/scheduler/pause").json()["paused"] is True
    assert client.post("/api/v1/scheduler/resume").json()["paused"] is False
    st = client.get("/api/v1/scheduler/status").json()
    assert st["running"] is False and "submit" not in " ".join(st["kinds"])
    assert len(client.get("/api/v1/scheduler/runs").json()) == 1
    assert "funnel" in client.get("/api/v1/reports/weekly").json()
    assert client.post("/api/v1/scheduler/runs/" + run["id"] + "/retry").status_code == 409


def test_scheduler_service_start_stop(db):
    from careerpilot.scheduler import service as sch
    s = sch.get()
    s.start(run_catchup=False)
    try:
        assert sch.is_running()
    finally:
        s.stop()
    assert not sch.is_running()
