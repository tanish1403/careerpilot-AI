"""Company briefs. Every claim carries source_url + retrieved_at; nothing is inferred or invented.
Interview themes without a source URL are flagged unverified."""
from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy.orm import Session

from ..core.untrusted import injection_flags
from ..db.base import utcnow
from ..db.models import Company, Job

transport: httpx.BaseTransport | None = None   # tests inject httpx.MockTransport
UA = "CareerPilotBot/0.1 (personal job-search assistant)"
MAX_BYTES = 500_000


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.desc = ""
        self.headings: list[str] = []
        self._tag = ""

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and not self.desc:
                self.desc = (a.get("content") or "").strip()

    def handle_endtag(self, tag):
        self._tag = ""

    def handle_data(self, data):
        d = data.strip()
        if not d:
            return
        if self._tag == "title" and not self.title:
            self.title = d
        elif self._tag in ("h1", "h2") and len(self.headings) < 5:
            self.headings.append(d)


def make_claim(text: str, source_url: str, retrieved_at: datetime | str) -> dict:
    if not source_url or not text.strip():
        raise ValueError("a claim requires text and a source URL")
    ts = retrieved_at.isoformat() if isinstance(retrieved_at, datetime) else retrieved_at
    return {"text": text.strip()[:500], "source_url": source_url, "retrieved_at": ts}


def robots_allows(client: httpx.Client, url: str) -> bool:
    p = urlparse(url)
    try:
        r = client.get(f"{p.scheme}://{p.netloc}/robots.txt")
    except httpx.HTTPError:
        return True   # robots unreachable: proceed conservatively with a single polite GET
    if r.status_code in (401, 403):
        return False
    if r.status_code >= 400:
        return True
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(UA, url)


def fetch_url(client: httpx.Client, url: str) -> tuple[list[dict], dict]:
    if urlparse(url).scheme not in ("http", "https"):
        return [], {"url": url, "status": "skipped", "reason": "unsupported scheme"}
    if not robots_allows(client, url):
        return [], {"url": url, "status": "blocked", "reason": "disallowed by robots.txt"}
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        return [], {"url": url, "status": "error", "reason": type(e).__name__}
    if r.status_code >= 400:
        return [], {"url": url, "status": "error", "reason": f"HTTP {r.status_code}"}
    now = utcnow()
    page = _Page()
    page.feed(r.text[:MAX_BYTES])
    claims = []
    if page.title:
        claims.append(make_claim(f"Page title: {page.title}", url, now))
    if page.desc:
        claims.append(make_claim(f"Self-description: {page.desc}", url, now))
    for h in page.headings:
        claims.append(make_claim(f"Page heading: {h}", url, now))
    flags = injection_flags(r.text[:MAX_BYTES])
    return claims, {"url": url, "status": "ok", "retrieved_at": now.isoformat(),
                    **({"warning": "possible prompt injection text on page ignored: " + ", ".join(flags)} if flags else {})}


def build_brief(db: Session, company: str, role: str | None = None, job_id: str | None = None,
                urls: list[str] | None = None, interview_notes: list[dict] | None = None) -> Company:
    row = db.query(Company).filter(Company.deleted_at.is_(None), Company.name == company).first()
    job = db.get(Job, job_id) if job_id else None
    if row is None:
        row = Company(name=company, brief={})
        db.add(row)
    urls = list(urls or [])
    if not urls and row.website:
        urls = [row.website]
    if urls and not row.website:
        row.website = urls[0]
    claims: list[dict] = []
    fetches: list[dict] = []
    if urls:
        with httpx.Client(transport=transport, timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as c:
            for u in urls[:5]:
                cl, meta = fetch_url(c, u)
                claims += cl
                fetches.append(meta)
    themes = []
    for n in interview_notes or []:
        text = (n.get("theme") or n.get("text") or "").strip()
        if not text:
            continue
        src = (n.get("source_url") or "").strip()
        themes.append({"theme": text, "source_url": src or None,
                       "retrieved_at": utcnow().isoformat() if src else None,
                       "unverified": not src,
                       "note": None if src else "No source provided; treat as unverified."})
    sources = sorted({c["source_url"] for c in claims} | {t["source_url"] for t in themes if t["source_url"]})
    ts = {c["source_url"]: c["retrieved_at"] for c in claims}
    row.brief = {"role": role, "job_id": job.id if job else None, "claims": claims, "fetches": fetches,
                 "interview_themes": themes,
                 "sources": [{"url": u, "retrieved_at": ts.get(u)} for u in sources],
                 "note": "Only sourced claims are listed; no facts were inferred." if claims else
                         "No sources were fetched. Provide company URLs to build a sourced brief."}
    row.brief_retrieved_at = utcnow() if claims else row.brief_retrieved_at
    db.flush()
    return row


def company_dict(c: Company) -> dict:
    b = c.brief or {}
    return {"id": c.id, "name": c.name, "website": c.website,
            "brief_retrieved_at": c.brief_retrieved_at.isoformat() if c.brief_retrieved_at else None,
            "claims": b.get("claims", []), "sources": b.get("sources", []),
            "interview_themes": b.get("interview_themes", []), "fetches": b.get("fetches", []),
            "note": b.get("note"), "role": b.get("role")}
