"""Shared helpers for Lane C tests: fixtures, MockTransport router, fake sleep, profile builder."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

FIX = Path(__file__).parent / "jobs"


def fixture_text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class Router:
    """Route requests by URL substring -> response factory. Records every request."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, object]] = []
        self.requests: list[httpx.Request] = []

    def add(self, needle: str, resp) -> "Router":
        self.routes.append((needle, resp))
        return self

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for needle, resp in self.routes:
            if needle in str(request.url):
                r = resp(request) if callable(resp) else resp
                return r
        return httpx.Response(404, text="not found")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def json_resp(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def html_resp(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "text/html"})


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


@pytest.fixture()
def sleeps():
    from careerpilot.job_connectors import http
    fs = FakeSleep()
    http.configure_runtime(sleep=fs)
    yield fs
    http.reset_runtime()


@pytest.fixture()
def use_router(sleeps):
    """Install a Router as the process-wide transport (used by services and routes)."""
    from careerpilot.job_connectors import http

    def install(router: Router) -> Router:
        http.configure_runtime(transport=router.transport, sleep=sleeps)
        return router
    return install


def make_profile(db, *, skills=(), unconfirmed_skills=(), experiences=(), education=(), projects=(),
                 location="Austin, TX", prefs=None, headline="Engineer"):
    """experiences: (title, company, start, end, bullets, confirmed)."""
    from careerpilot.db.models import CandidateProfile, Education, Experience, Project, Skill
    p = CandidateProfile(headline=headline, location=location, preferences=prefs or {}, links={}, version=1)
    db.add(p)
    db.flush()
    for s in skills:
        db.add(Skill(profile_id=p.id, name=s, status="confirmed"))
    for s in unconfirmed_skills:
        db.add(Skill(profile_id=p.id, name=s, status="proposed"))
    for t, c, a, b, bullets, conf in experiences:
        db.add(Experience(profile_id=p.id, title=t, company=c, start_date=a, end_date=b, bullets=list(bullets),
                          status="confirmed" if conf else "proposed"))
    for deg, fld, inst, conf in education:
        db.add(Education(profile_id=p.id, degree=deg, field=fld, institution=inst,
                         status="confirmed" if conf else "proposed"))
    for name, desc, tech, conf in projects:
        db.add(Project(profile_id=p.id, name=name, description=desc, technologies=list(tech),
                       status="confirmed" if conf else "proposed"))
    db.commit()
    return p
