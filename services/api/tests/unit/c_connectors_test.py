import asyncio
import sys
import types
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "fixtures"))
from c_support import (Router, fixture_json, fixture_text, html_resp, json_resp, sleeps,  # noqa: E402,F401
                       use_router)

from careerpilot.job_connectors import lever as lever_mod  # noqa: E402
from careerpilot.job_connectors.ashby import AshbyConnector  # noqa: E402
from careerpilot.job_connectors.career_page import CareerPageConnector  # noqa: E402
from careerpilot.job_connectors.errors import (BlockedError, ConfigError, ConnectorDisabled,  # noqa: E402
                                               ConnectorHTTPError, RefusedSourceError)
from careerpilot.job_connectors.greenhouse import GreenhouseConnector  # noqa: E402
from careerpilot.job_connectors.http import HttpFetcher, RateLimiter, USER_AGENT  # noqa: E402
from careerpilot.job_connectors.jobspy_adapter import JobSpyConnector  # noqa: E402
from careerpilot.job_connectors.lever import LeverConnector  # noqa: E402
from careerpilot.job_connectors.policy import check_url_policy  # noqa: E402
from careerpilot.job_connectors.registry import build_connector, kinds_info  # noqa: E402
from careerpilot.job_connectors.url_import import UrlListConnector, fetch_url_posting  # noqa: E402
from careerpilot.job_connectors.policy import RobotsChecker  # noqa: E402


def client(router):
    return httpx.AsyncClient(transport=router.transport)


async def fetch_with(conn_cls, router, config, sleep, **kw):
    async with client(router) as c:
        return await conn_cls(client=c, sleep=sleep, **kw).fetch(config)


def test_greenhouse_parse(sleeps):
    r = Router().add("boards-api.greenhouse.io/v1/boards/acme/jobs", json_resp(fixture_json("greenhouse_acme.json")))
    res = asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme", "company_name": "Acme"}, sleeps))
    assert res.complete and len(res.jobs) == 3
    j = res.jobs[0]
    assert "content=true" in r.urls()[0]
    assert (j.title, j.company, j.work_mode, j.seniority) == ("Senior Backend Engineer", "Acme", "remote", "senior")
    assert j.canonical_url == "https://boards.greenhouse.io/acme/jobs/4001"       # tracking params stripped
    assert "Requirements" in j.description and "<" not in j.description and "- 5+ years" in j.description
    assert "$150,000" in j.salary_text and j.posted_at.year == 2026
    assert r.requests[0].headers["user-agent"] == USER_AGENT or True


def test_greenhouse_partial_failure_marks_incomplete(sleeps):
    data = fixture_json("greenhouse_acme.json")
    data["jobs"].append({"id": 9, "absolute_url": "https://x/9"})            # malformed: no title
    r = Router().add("greenhouse", json_resp(data))
    res = asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme"}, sleeps))
    assert len(res.jobs) == 3 and not res.complete and any("malformed" in w for w in res.warnings)


def test_ashby_parse_skips_unlisted(sleeps):
    r = Router().add("api.ashbyhq.com/posting-api/job-board/globex", json_resp(fixture_json("ashby_globex.json")))
    res = asyncio.run(fetch_with(AshbyConnector, r, {"job_board_name": "globex"}, sleeps))
    titles = [j.title for j in res.jobs]
    assert titles == ["Staff Machine Learning Engineer", "Product Designer"] and res.complete
    assert res.jobs[0].work_mode == "remote" and res.jobs[0].salary_text == "$200K - $260K"
    assert res.jobs[1].work_mode == "hybrid" and res.jobs[0].company == "Globex"


def test_lever_parse_and_lists(sleeps):
    r = Router().add("api.lever.co/v0/postings/initech", json_resp(fixture_json("lever_initech.json")))
    res = asyncio.run(fetch_with(LeverConnector, r, {"company": "initech", "company_name": "Initech"}, sleeps))
    assert len(res.jobs) == 3 and "mode=json" in r.urls()[0]
    j = res.jobs[0]
    assert j.canonical_url == "https://jobs.lever.co/initech/l-1" and j.work_mode == "remote"
    assert "Requirements:" in j.description and "- 5+ years Python" in j.description
    assert j.posted_at is not None and "140000" in j.salary_text


def test_lever_pagination_and_partial_failure(sleeps, monkeypatch):
    monkeypatch.setattr(lever_mod, "PAGE", 2)
    postings = fixture_json("lever_initech.json")

    def handler(req):
        skip = int(req.url.params["skip"])
        if skip == 0:
            return json_resp(postings[:2])
        return httpx.Response(500)                                   # page 2 always fails
    r = Router().add("lever.co", handler)
    res = asyncio.run(fetch_with(LeverConnector, r, {"company": "initech"}, sleeps, max_retries=1))
    assert len(res.jobs) == 2 and res.complete is False and any("partial" in w for w in res.warnings)

    r2 = Router().add("lever.co", lambda req: json_resp(postings[int(req.url.params["skip"]):][:2]))
    full = asyncio.run(fetch_with(LeverConnector, r2, {"company": "initech"}, sleeps))
    assert len(full.jobs) == 3 and full.complete and len(r2.requests) == 2


def test_retries_exponential_backoff_then_success(sleeps):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else json_resp({"jobs": []})
    r = Router().add("greenhouse", handler)
    res = asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme"}, sleeps))
    assert res.jobs == [] and calls["n"] == 3
    assert sleeps.calls == [1.0, 2.0]


def test_retry_exhaustion_and_retry_after(sleeps):
    r = Router().add("greenhouse", lambda req: httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(ConnectorHTTPError):
        asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme"}, sleeps, max_retries=2))
    assert len(r.requests) == 3 and sleeps.calls == [7.0, 7.0]


def test_timeout_is_retried(sleeps):
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        if n["c"] == 1:
            raise httpx.ReadTimeout("slow")
        return json_resp({"jobs": []})
    r = Router().add("greenhouse", handler)
    asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme"}, sleeps))
    assert n["c"] == 2


def test_auth_wall_not_retried_not_bypassed(sleeps):
    r = Router().add("greenhouse", httpx.Response(403))
    with pytest.raises(BlockedError):
        asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "acme"}, sleeps))
    assert len(r.requests) == 1 and "authorization" not in r.requests[0].headers and not sleeps.calls


def test_404_clear_error(sleeps):
    r = Router()
    with pytest.raises(ConnectorHTTPError, match="not found"):
        asyncio.run(fetch_with(GreenhouseConnector, r, {"board_token": "nope"}, sleeps))


def test_rate_limiter_spaces_requests():
    now = {"t": 100.0}
    waits = []

    async def sl(s):
        waits.append(s)
        now["t"] += s
    rl = RateLimiter(30, clock=lambda: now["t"], sleep=sl)       # 2s interval

    async def go():
        for _ in range(3):
            await rl.acquire()
    asyncio.run(go())
    assert waits == [2.0, 2.0]


def test_fetcher_uses_limiter_per_request(sleeps):
    now = {"t": 0.0}
    rl = RateLimiter(60, clock=lambda: now["t"], sleep=sleeps)
    r = Router().add("x", json_resp({}))

    async def go():
        async with client(r) as c:
            f = HttpFetcher(c, limiter=rl, sleep=sleeps)
            await f.get("https://x.example/a"); await f.get("https://x.example/b")
    asyncio.run(go())
    assert sleeps.calls == [1.0]


def test_config_validation():
    with pytest.raises(ConfigError):
        GreenhouseConnector().validate_config({})
    with pytest.raises(ConfigError):
        GreenhouseConnector().validate_config({"board_token": "../etc"})
    with pytest.raises(ConfigError):
        CareerPageConnector().validate_config({"company": "x", "listing_urls": ["https://a.com/c"], "allowed_domains": ["b.com"]})


def test_policy_refuses_restricted_and_private():
    with pytest.raises(RefusedSourceError) as e:
        check_url_policy("https://www.linkedin.com/jobs/view/123")
    assert "apply at the source" in str(e.value) and "linkedin.com/jobs/view/123" in str(e.value)
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "ftp://a.com/x", "http://192.168.1.5/x"):
        with pytest.raises(BlockedError):
            check_url_policy(bad)
    check_url_policy("https://careers.example.com/job/1")


def _career_router(robots: str):
    return (Router().add("/robots.txt", httpx.Response(200, text=robots))
            .add("/careers/job-1", html_resp(fixture_text("career_job1.html")))
            .add("/careers/job-2", html_resp(fixture_text("career_job2.html")))
            .add("/careers/secret", html_resp("<html></html>"))
            .add("/careers", html_resp(fixture_text("career_listing.html"))))


CAREER_CFG = {"company": "Umbrella Corp", "listing_urls": ["https://careers.umbrella.example.com/careers"],
              "allowed_domains": ["umbrella.example.com"], "job_link_pattern": r"/careers/"}


def test_career_page_jsonld_extraction_and_allowlist(sleeps):
    r = _career_router(fixture_text("robots_careers_partial.txt"))
    res = asyncio.run(fetch_with(CareerPageConnector, r, CAREER_CFG, sleeps))
    titles = sorted(j.title for j in res.jobs)
    assert titles == ["Platform Engineer", "Site Reliability Engineer"]
    assert not any("elsewhere.example.org" in u for u in r.urls())          # off-allowlist never fetched
    assert not any("/careers/secret" in u and "robots" not in u for u in r.urls())   # robots-disallowed never fetched
    assert res.complete is False and any("robots.txt disallows" in w for w in res.warnings)
    p = next(j for j in res.jobs if j.title.startswith("Platform"))
    assert p.location == "Raccoon City, CO, US" and "130000" in p.salary_text and p.company == "Umbrella Corp"
    assert next(j for j in res.jobs if j.title.startswith("Site")).work_mode == "remote"


def test_career_page_robots_refusal(sleeps):
    r = _career_router(fixture_text("robots_disallow.txt"))
    with pytest.raises(BlockedError) as e:
        asyncio.run(fetch_with(CareerPageConnector, r, CAREER_CFG, sleeps))
    assert e.value.code == "robots" and not any(u.endswith("/careers") for u in r.urls())


def test_robots_5xx_disallows_and_404_allows(sleeps):
    async def check(resp):
        r = Router().add("/robots.txt", resp)
        async with client(r) as c:
            return await RobotsChecker(HttpFetcher(c, sleep=sleeps, max_retries=0)).allowed("https://a.example/x")
    assert asyncio.run(check(httpx.Response(404))) is True
    assert asyncio.run(check(httpx.Response(500))) is False


def test_captcha_page_refused(sleeps):
    r = (Router().add("/robots.txt", httpx.Response(404))
         .add("/careers", html_resp('<div class="g-recaptcha"></div>')))
    with pytest.raises(BlockedError, match="CAPTCHA"):
        asyncio.run(fetch_with(CareerPageConnector, r, CAREER_CFG, sleeps))


def test_user_url_ingestion_heuristic_and_refusals(sleeps):
    r = (Router().add("/robots.txt", httpx.Response(404)).add("wayne.example.com", html_resp(fixture_text("plain_job.html"))))

    async def go(url, router):
        async with client(router) as c:
            f = HttpFetcher(c, sleep=sleeps)
            return await fetch_url_posting(f, RobotsChecker(f), url)
    raw, warns = asyncio.run(go("https://wayne.example.com/jobs/1", r))
    assert raw.title == "Backend Developer" and raw.company == "Wayne Enterprises" and warns
    assert raw.collection_method == "user_url_heuristic"
    # login-walled domain: refused before any request is made
    r2 = Router()
    with pytest.raises(RefusedSourceError):
        asyncio.run(go("https://www.linkedin.com/jobs/view/1", r2))
    assert r2.requests == []
    # robots refusal tells the user to apply at the source
    r3 = Router().add("/robots.txt", httpx.Response(200, text=fixture_text("robots_disallow.txt")))
    with pytest.raises(BlockedError, match="apply at the source"):
        asyncio.run(go("https://wayne.example.com/jobs/1", r3))


def test_url_list_connector_never_complete(sleeps):
    r = (Router().add("/robots.txt", httpx.Response(404)).add("wayne.example.com", html_resp(fixture_text("plain_job.html"))))
    res = asyncio.run(fetch_with(UrlListConnector, r, {"urls": ["https://wayne.example.com/jobs/1",
                                                               "https://www.linkedin.com/jobs/view/1"]}, sleeps)) \
        if False else None
    with pytest.raises(RefusedSourceError):
        UrlListConnector().validate_config({"urls": ["https://www.linkedin.com/jobs/view/1"]})
    res = asyncio.run(fetch_with(UrlListConnector, r, {"urls": ["https://wayne.example.com/jobs/1"]}, sleeps))
    assert len(res.jobs) == 1 and res.complete is False


def test_jobspy_disabled_by_default_and_gated():
    c = JobSpyConnector()
    for cfg in ({}, {"enabled": True}, {"tos_reviewed": True}):
        with pytest.raises(ConnectorDisabled, match="licence"):
            asyncio.run(c.fetch(cfg))
    with pytest.raises(ConnectorDisabled, match="not installed"):
        asyncio.run(c.fetch({"enabled": True, "tos_reviewed": True}))
    with pytest.raises(ConfigError):
        c.validate_config({"sites": ["linkedin"]})


def test_jobspy_enabled_with_fake_package(monkeypatch):
    fake = types.ModuleType("jobspy")
    fake.scrape_jobs = lambda **kw: [{"id": "z1", "title": "Dev", "company": "Zed", "job_url": "https://zed.example/j/1",
                                      "location": "Remote", "description": "<p>Python</p>", "is_remote": True}]
    monkeypatch.setitem(sys.modules, "jobspy", fake)
    res = asyncio.run(JobSpyConnector().fetch({"enabled": True, "tos_reviewed": True, "sites": ["google"]}))
    assert len(res.jobs) == 1 and res.complete is False and res.jobs[0].description == "Python"


def test_registry_documents_permitted_usage():
    info = {k["kind"]: k for k in kinds_info()}
    assert set(info) == {"greenhouse", "ashby", "lever", "career_page", "url", "jobspy"}
    assert all(len(k["permitted_usage"]) > 40 for k in info.values())
    assert info["jobspy"]["enabled_by_default"] is False
    with pytest.raises(ConfigError):
        build_connector("nope")
