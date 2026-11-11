from __future__ import annotations

import hashlib

from .base import BaseConnector
from .errors import BlockedError, ConfigError, ConnectorError
from .extract import (extract_links, heuristic_posting, jobposting_to_raw, jsonld_job_postings,
                      looks_blocked)
from .interface import ConnectorResult, RawJob
from .normalize import canonical_url
from .policy import RobotsChecker, check_url_policy, domain_allowed_by, host_of


class CareerPageConnector(BaseConnector):
    kind = "career_page"
    label = "Company career page (allowlisted)"
    permitted_usage = ("Fetches a company's own public career pages listed in the per-site allowlisted "
                       "config, extracting schema.org JobPosting JSON-LD. robots.txt is always checked "
                       "(cannot be disabled), only allowed_domains are followed, login/CAPTCHA pages are "
                       "never bypassed. Limitation: pages without JSON-LD yield nothing; results are "
                       "incomplete when max_jobs truncates or any page is refused.")
    config_schema = {"company": {"type": "string", "required": True},
                     "listing_urls": {"type": "array", "required": True},
                     "allowed_domains": {"type": "array", "required": True},
                     "job_link_pattern": {"type": "string"}, "job_link_selector": {"type": "string"},
                     "max_jobs": {"type": "integer", "default": 50}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        if not str(cfg.get("company") or "").strip():
            raise ConfigError("config.company is required")
        urls, allowed = cfg.get("listing_urls"), cfg.get("allowed_domains")
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
            raise ConfigError("config.listing_urls must be a non-empty list of URLs")
        if not isinstance(allowed, list) or not allowed:
            raise ConfigError("config.allowed_domains (explicit per-site allowlist) is required")
        for u in urls:
            check_url_policy(u)
            if not domain_allowed_by(host_of(u), allowed):
                raise ConfigError(f"listing URL host '{host_of(u)}' is not in allowed_domains")
        cfg["max_jobs"] = max(1, min(int(cfg.get("max_jobs") or 50), 500))
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        res = ConnectorResult()
        async with self.http() as http:
            robots = RobotsChecker(http)
            seen: dict[str, RawJob] = {}
            detail_urls: list[str] = []
            for lu in cfg["listing_urls"]:
                if not await robots.allowed(lu):
                    raise BlockedError(f"robots.txt disallows fetching {lu}; not fetched. "
                                       "Open the page yourself to apply at the source.", lu, "robots")
                html = (await http.get(lu)).text
                if looks_blocked(html):
                    raise BlockedError(f"{host_of(lu)} served a bot challenge/CAPTCHA; not bypassed.", lu)
                for node in jsonld_job_postings(html):
                    try:
                        r = jobposting_to_raw(node, lu, kind=self.kind, method="career_page_jsonld",
                                              default_company=cfg["company"])
                        seen.setdefault(r.canonical_url, r)
                    except ValueError as e:
                        res.warnings.append(str(e)); res.complete = False
                detail_urls += [u for u in extract_links(
                    html, lu, selector=cfg.get("job_link_selector"), pattern=cfg.get("job_link_pattern"),
                    allowed_domains=cfg["allowed_domains"]) if u not in detail_urls]
            if len(detail_urls) > cfg["max_jobs"]:
                res.complete = False
                res.warnings.append(f"{len(detail_urls)} job links found; truncated to max_jobs={cfg['max_jobs']}")
                detail_urls = detail_urls[:cfg["max_jobs"]]
            for u in detail_urls:
                if u in seen:
                    continue
                try:
                    if not await robots.allowed(u):
                        res.complete = False
                        res.warnings.append(f"robots.txt disallows {u}; skipped")
                        continue
                    html = (await http.get(u)).text
                    if looks_blocked(html):
                        res.complete = False
                        res.warnings.append(f"bot challenge at {u}; skipped (not bypassed)")
                        continue
                    nodes = jsonld_job_postings(html)
                    if not nodes:
                        res.complete = False
                        res.warnings.append(f"no JobPosting JSON-LD at {u}; skipped")
                        continue
                    r = jobposting_to_raw(nodes[0], u, kind=self.kind, method="career_page_jsonld",
                                          default_company=cfg["company"])
                    seen.setdefault(r.canonical_url, r)
                except ConnectorError as e:
                    res.complete = False
                    res.warnings.append(f"{u}: {e}")
        res.jobs = list(seen.values())
        return res
