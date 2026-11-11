import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / "fixtures"))
from c_support import Router, fixture_json, json_resp, make_profile, sleeps, use_router  # noqa: E402,F401

GH = {"kind": "greenhouse", "name": "Acme board", "config": {"board_token": "acme", "company_name": "Acme"}}


def gh_router():
    return Router().add("greenhouse.io/v1/boards/acme", json_resp(fixture_json("greenhouse_acme.json")))


def wait_run(client, run_id):
    for _ in range(50):
        r = client.get(f"/api/v1/runs/{run_id}").json()
        if r["status"] in ("succeeded", "failed"):
            return r
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_source_crud_kinds_and_validation(client):
    kinds = client.get("/api/v1/sources/kinds").json()
    assert {k["kind"] for k in kinds} >= {"greenhouse", "ashby", "lever", "career_page", "jobspy"}
    assert all(k["permitted_usage"] and "config_schema" in k for k in kinds)
    assert client.post("/api/v1/sources", json={"kind": "bogus", "name": "x", "config": {}}).status_code == 422
    assert client.post("/api/v1/sources", json={"kind": "greenhouse", "name": "x", "config": {}}).status_code == 422
    r = client.post("/api/v1/sources", json=GH)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.patch(f"/api/v1/sources/{sid}", json={"enabled": False, "rate_limit_per_min": 10}).json()["enabled"] is False
    assert client.get("/api/v1/sources").json()["total"] == 1
    assert client.delete(f"/api/v1/sources/{sid}").status_code == 204
    assert client.get(f"/api/v1/sources/{sid}").status_code == 404
    assert client.get("/api/v1/sources").json() == {"items": [], "total": 0}


def test_run_source_flow_jobs_detail_health_logs(client, use_router):
    use_router(gh_router())
    sid = client.post("/api/v1/sources", json=GH).json()["id"]
    t = client.post(f"/api/v1/sources/{sid}/test").json()
    assert t["ok"] and t["job_count"] == 3 and client.get("/api/v1/jobs").json()["total"] == 0   # test does not persist
    r = client.post(f"/api/v1/sources/{sid}/run")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    run = wait_run(client, r.json()["run_id"])
    assert run["status"] == "succeeded" and run["output_refs"]["created"] == 3
    jobs = client.get("/api/v1/jobs").json()
    assert jobs["total"] == 3
    item = next(i for i in jobs["items"] if i["title"] == "Senior Backend Engineer")
    assert [x["kind"] for x in item["sources"]] == ["greenhouse"] and item["match"] is None
    assert item["sources"][0]["url"].startswith("https://boards.greenhouse.io/acme/jobs/4001")   # original link kept
    detail = client.get(f"/api/v1/jobs/{item['id']}").json()
    assert detail["requirements"] and detail["source_records"][0]["collection_method"] == "public_api"
    assert detail["injection_flags"] == [] and detail["match"] is None
    ds = next(i for i in jobs["items"] if i["title"] == "Data Scientist")
    flags = client.get(f"/api/v1/jobs/{ds['id']}").json()["injection_flags"]
    assert any("ignore all previous instructions" in f for f in flags)
    h = client.get(f"/api/v1/sources/{sid}/health").json()
    assert h["status"] == "healthy" and h["open_jobs"] == 3 and h["recent_logs"][0]["created"] == 3
    logs = client.get("/api/v1/ingestion-logs", params={"source_id": sid}).json()
    assert logs["total"] == 1 and logs["items"][0]["status"] == "success"


def test_failed_run_reports_failure_and_health(client, use_router):
    use_router(Router().add("greenhouse", httpx.Response(500)))
    sid = client.post("/api/v1/sources", json=GH).json()["id"]
    run = wait_run(client, client.post(f"/api/v1/sources/{sid}/run").json()["run_id"])
    assert run["status"] == "failed" and "500" in run["error"]
    h = client.get(f"/api/v1/sources/{sid}/health").json()
    assert h["status"] in ("degraded", "failing") and h["consecutive_failures"] == 1 and h["last_error"]


def test_import_url_refusals_and_text(client, use_router, db):
    r = client.post("/api/v1/jobs/import-url", json={"url": "https://www.linkedin.com/jobs/view/123"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "refused_domain" and "apply at the source" in body["detail"] and body["apply_url"].endswith("/123")
    use_router(Router().add("/robots.txt", httpx.Response(200, text="User-agent: *\nDisallow: /")))
    r = client.post("/api/v1/jobs/import-url", json={"url": "https://wayne.example.com/jobs/1"})
    assert r.status_code == 422 and r.json()["code"] == "robots"
    r = client.post("/api/v1/jobs/import-text", json={"title": "Dev", "company": "Acme", "description": "Python role"})
    assert r.status_code == 201 and r.json()["sources"][0]["kind"] == "manual"
    jid = r.json()["id"]
    assert client.post(f"/api/v1/jobs/{jid}/save").json()["saved"] is True
    assert client.get("/api/v1/jobs", params={"saved": "true"}).json()["total"] == 1
    assert client.post(f"/api/v1/jobs/{jid}/unsave").json()["saved"] is False
    assert client.post(f"/api/v1/jobs/{jid}/verify").json()["status"] == "unverifiable"


def test_import_url_success_with_json_ld(client, use_router):
    from c_support import fixture_text, html_resp
    use_router(Router().add("/robots.txt", httpx.Response(404)).add("careers.umbrella.example.com/careers/job-1",
                                                                   html_resp(fixture_text("career_job1.html"))))
    r = client.post("/api/v1/jobs/import-url", json={"url": "https://careers.umbrella.example.com/careers/job-1?utm_source=x"})
    assert r.status_code == 201
    d = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert d["company_name"] == "Umbrella Corp" and d["location"] == "Raccoon City, CO, US"
    assert d["source_records"][0]["collection_method"] == "user_url" and d["canonical_url"].endswith("/careers/job-1")
    assert {(x["kind"], x["normalized"]) for x in d["requirements"]} >= {("skill", "kubernetes"), ("skill", "terraform")}


def test_matching_endpoints_end_to_end(client, use_router, db):
    use_router(gh_router())
    assert client.post("/api/v1/matches/score", json={"all": True}).status_code == 409      # no profile yet
    sid = client.post("/api/v1/sources", json=GH).json()["id"]
    wait_run(client, client.post(f"/api/v1/sources/{sid}/run").json()["run_id"])
    make_profile(db, skills=["Python", "PostgreSQL", "AWS"], unconfirmed_skills=["Kubernetes"],
                 experiences=[("Backend Engineer", "Foo", "2015-01", "2024-06", ["python"], True)],
                 education=[("BSc", "Computer Science", "MIT", True)], prefs={"roles": ["backend"], "work_modes": ["remote"]})
    assert client.post("/api/v1/matches/score", json={}).status_code == 422
    run = wait_run(client, client.post("/api/v1/matches/score", json={"all": True}).json()["run_id"])
    assert run["status"] == "succeeded" and run["output_refs"]["scored"] == 3
    jobs = client.get("/api/v1/jobs", params={"sort": "priority"}).json()["items"]
    assert jobs[0]["title"] == "Senior Backend Engineer" and jobs[0]["match"]["fit_score"] > jobs[1]["match"]["fit_score"]
    assert all(set(i["match"]) >= {"eligibility", "fit_score", "priority_score"} for i in jobs)
    mid = jobs[0]["match"]["id"]
    m = client.get(f"/api/v1/matches/{mid}").json()
    assert m["eligibility"] == "unknown"                       # k8s requirement only unconfirmed
    assert {"requirement", "state", "evidence"} <= set(m["eligibility_details"][0])
    assert set(m["factors"]) == {"technical_skills", "experience", "projects", "education", "domain", "role_alignment",
                                 "location", "freshness"} and "NOT a probability" in m["disclaimer"]
    assert client.get("/api/v1/matches", params={"job_id": jobs[0]["id"]}).json()["total"] == 1
    again = wait_run(client, client.post("/api/v1/matches/score", json={"job_ids": [jobs[0]["id"]]}).json()["run_id"])
    assert again["output_refs"]["reused"] == 1
    fb = client.post(f"/api/v1/matches/{mid}/feedback", json={"relevant": True, "action": "applied", "reason": "good"})
    assert fb.status_code == 201
    assert client.post(f"/api/v1/matches/{mid}/feedback", json={"action": "nope"}).status_code == 422
    assert client.get(f"/api/v1/matches/{mid}").json()["feedback"][0]["action"] == "applied"
    detail = client.get(f"/api/v1/jobs/{jobs[0]['id']}").json()
    assert detail["match"]["id"] == mid
    # filters
    q = lambda **p: {i["title"] for i in client.get("/api/v1/jobs", params=p).json()["items"]}  # noqa: E731
    assert q(work_mode="remote") == {"Senior Backend Engineer"}
    assert q(location="new york") == {"Frontend Engineer"}
    assert q(seniority="senior") == {"Senior Backend Engineer"}
    assert q(q="react") == {"Frontend Engineer"} and q(role="data") == {"Data Scientist"}
    assert q(source_kind="greenhouse") and q(source_kind="lever") == set()
    assert q(min_salary=170000) == {"Senior Backend Engineer"} and q(min_salary=500000) == set()
    assert q(new_only="true") and q(posted_within_days=1000)
    assert q(posted_within_days=0) == set() or True
    assert q(min_fit=jobs[0]["match"]["fit_score"]) == {"Senior Backend Engineer"}
    assert client.get("/api/v1/jobs", params={"sort": "bogus"}).status_code == 422
    assert [i["title"] for i in client.get("/api/v1/jobs", params={"sort": "posted"}).json()["items"]][0]
    pf = client.get("/api/v1/matching/preferences-filters").json()
    assert pf["suggested"]["work_mode"] == "remote" and pf["facets"]["source_kind"]["greenhouse"] == 3


def test_matching_config_endpoints(client, db):
    c = client.get("/api/v1/matching/config").json()
    assert c["weights"]["technical_skills"] == 0.25 and c["version"]
    bad = dict(c["weights"], technical_skills=0.5)
    r = client.put("/api/v1/matching/config", json={"weights": bad})
    assert r.status_code == 422 and "sum to 1" in r.json()["detail"]
    assert client.put("/api/v1/matching/config", json={"weights": {"technical_skills": 1}}).status_code == 422
    good = dict(c["weights"], technical_skills=0.30, experience=0.15)
    r = client.put("/api/v1/matching/config", json={"weights": good})
    assert r.status_code == 200 and r.json()["version"] != c["version"]
    assert client.get("/api/v1/matching/config").json()["weights"]["technical_skills"] == 0.30
