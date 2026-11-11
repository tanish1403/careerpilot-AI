"""schema.org JobPosting (JSON-LD) extraction with an HTML heuristic fallback."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


from .interface import RawJob
from .normalize import (canonical_url, extract_salary_text, html_to_text, infer_seniority,
                        infer_work_mode, parse_dt)

_BLOCK_MARKERS = re.compile(r"(g-recaptcha|h-captcha|cf-challenge|cf-turnstile|are you a robot|"
                            r"verify you are human|access denied|attention required)", re.I)


def looks_blocked(html: str) -> bool:
    return bool(_BLOCK_MARKERS.search((html or "")[:20000]))


def looks_login_wall(url: str, html: str) -> bool:
    path = urlsplit(url).path.lower()
    soup_text = (html or "")[:8000].lower()
    return bool(re.search(r"/(login|signin|sign-in|sso|auth)(/|$)", path)) or (
        'type="password"' in soup_text and "jobposting" not in soup_text)


def _iter_nodes(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _iter_nodes(o)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "mainEntity", "itemListElement", "item"):
            if k in obj:
                yield from _iter_nodes(obj[k])


def _is_job(node: dict) -> bool:
    t = node.get("@type")
    return (t == "JobPosting") or (isinstance(t, list) and "JobPosting" in t)


def jsonld_job_postings(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        txt = (tag.string or tag.get_text() or "").strip()
        if not txt:
            continue
        try:
            data = json.loads(txt, strict=False)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", txt), strict=False)
            except ValueError:
                continue
        out.extend(n for n in _iter_nodes(data) if _is_job(n))
    return out


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _location(node: dict) -> str | None:
    locs = node.get("jobLocation")
    parts: list[str] = []
    for loc in (locs if isinstance(locs, list) else [locs] if locs else []):
        if isinstance(loc, str):
            parts.append(loc)
            continue
        addr = loc.get("address", loc) if isinstance(loc, dict) else {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        country = addr.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        bits = [_s(addr.get("addressLocality")), _s(addr.get("addressRegion")), _s(country)]
        s = ", ".join(b for b in bits if b)
        if s:
            parts.append(s)
    if not parts and node.get("applicantLocationRequirements"):
        req = node["applicantLocationRequirements"]
        req = req if isinstance(req, list) else [req]
        parts = [_s(r.get("name")) for r in req if isinstance(r, dict) and _s(r.get("name"))]
    return "; ".join(dict.fromkeys(parts)) or None


def _salary(node: dict) -> str | None:
    bs = node.get("baseSalary")
    if not isinstance(bs, dict):
        return None
    val = bs.get("value", {})
    cur = _s(bs.get("currency"))
    if isinstance(val, dict):
        lo, hi, unit = val.get("minValue"), val.get("maxValue"), _s(val.get("unitText"))
        v = val.get("value")
        rng = f"{lo}-{hi}" if lo is not None and hi is not None else str(v if v is not None else lo or hi or "")
    else:
        rng, unit = str(val), ""
    s = " ".join(x for x in (cur, rng, f"per {unit.lower()}" if unit else "") if x).strip()
    return s or None


def _company(node: dict) -> str:
    org = node.get("hiringOrganization")
    return _s(org.get("name")) if isinstance(org, dict) else _s(org)


def jobposting_to_raw(node: dict, page_url: str, *, kind: str, method: str,
                      default_company: str = "") -> RawJob:
    title = _s(node.get("title") or node.get("name"))
    if not title:
        raise ValueError("JobPosting without title")
    url = _s(node.get("url")) or page_url
    url = urljoin(page_url, url)
    desc = html_to_text(_s(node.get("description")))
    loc = _location(node)
    remote = _s(node.get("jobLocationType")).upper() == "TELECOMMUTE"
    ident = node.get("identifier")
    ext = _s(ident.get("value") if isinstance(ident, dict) else ident) or \
        hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]
    salary = _salary(node) or extract_salary_text(desc)
    return RawJob(
        source_kind=kind, external_id=str(ext), source_url=url, canonical_url=canonical_url(url),
        title=title, company=_company(node) or default_company or "Unknown company", location=loc,
        work_mode="remote" if remote else infer_work_mode(loc, title),
        description=desc, salary_text=salary, seniority=infer_seniority(title),
        posted_at=parse_dt(node.get("datePosted")), collection_method=method,
        raw={"jsonld": node, "validThrough": node.get("validThrough")})


def heuristic_posting(html: str, page_url: str, *, kind: str, method: str) -> RawJob | None:
    """Low-confidence fallback for pages without JSON-LD: title + visible text."""
    soup = BeautifulSoup(html or "", "html.parser")
    og = lambda p: (soup.find("meta", property=p) or {}).get("content")  # noqa: E731
    h1 = soup.find("h1")
    title = (h1.get_text(strip=True) if h1 else "") or _s(og("og:title")) or \
        (soup.title.get_text(strip=True) if soup.title else "")
    if not title:
        return None
    main = soup.find("main") or soup.find("article") or soup.body or soup
    desc = html_to_text(str(main))
    if len(desc) < 80:
        return None
    company = _s(og("og:site_name")) or urlsplit(page_url).hostname or "Unknown company"
    return RawJob(
        source_kind=kind, external_id=hashlib.sha1(canonical_url(page_url).encode()).hexdigest()[:16],
        source_url=page_url, canonical_url=canonical_url(page_url), title=title[:300],
        company=company, work_mode=infer_work_mode(title, desc[:1500]), description=desc,
        salary_text=extract_salary_text(desc), seniority=infer_seniority(title),
        collection_method=method + "_heuristic", raw={"heuristic": True})


def extract_links(html: str, base_url: str, *, selector: str | None, pattern: str | None,
                  allowed_domains: list[str]) -> list[str]:
    from .policy import domain_allowed_by
    soup = BeautifulSoup(html or "", "html.parser")
    anchors = soup.select(selector) if selector else soup.find_all("a", href=True)
    rx = re.compile(pattern) if pattern else None
    out: list[str] = []
    for a in anchors:
        href = a.get("href")
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        u = urljoin(base_url, href)
        if rx and not rx.search(u):
            continue
        if not domain_allowed_by(urlsplit(u).hostname or "", allowed_domains):
            continue
        c = canonical_url(u)
        if c not in out:
            out.append(c)
    return out
