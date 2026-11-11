"""User-supplied URL ingestion (single page) and the saved-URL-list connector kind."""
from __future__ import annotations

from .base import BaseConnector
from .errors import BlockedError, ConfigError, ConnectorError
from .extract import (heuristic_posting, jobposting_to_raw, jsonld_job_postings, looks_blocked,
                      looks_login_wall)
from .http import HttpFetcher
from .interface import ConnectorResult, RawJob
from .policy import RobotsChecker, check_url_policy


async def fetch_url_posting(http: HttpFetcher, robots: RobotsChecker, url: str, *,
                            kind: str = "url") -> tuple[RawJob, list[str]]:
    check_url_policy(url)
    if not await robots.allowed(url):
        raise BlockedError("robots.txt disallows automated fetching of this page, so it was not "
                           f"fetched. Open it yourself and apply at the source: {url}. You can paste "
                           "the description with 'Import text' instead.", url, "robots")
    resp = await http.get(url)
    final = str(resp.url)
    check_url_policy(final)          # a redirect must not land on a restricted host
    html = resp.text
    if looks_blocked(html):
        raise BlockedError("The site served a bot challenge/CAPTCHA, which CareerPilot does not "
                           f"bypass. Open the posting yourself to apply at the source: {url}", url)
    nodes = jsonld_job_postings(html)
    warnings: list[str] = []
    if nodes:
        return jobposting_to_raw(nodes[0], final, kind=kind, method="user_url"), warnings
    if looks_login_wall(final, html):
        raise BlockedError("This page looks login-walled; CareerPilot will not fetch it. Open it "
                           f"yourself to apply at the source: {url}", url, "login_wall")
    raw = heuristic_posting(html, final, kind=kind, method="user_url")
    if raw is None:
        raise ConnectorError("No job posting could be extracted from this page (no schema.org "
                             "JobPosting data). Use 'Import text' to paste the description.")
    warnings.append("No structured JobPosting data found; extracted with low-confidence heuristics")
    return raw, warnings


class UrlListConnector(BaseConnector):
    kind = "url"
    label = "Saved job URLs"
    permitted_usage = ("Re-reads individual job-posting URLs you supplied (JSON-LD, robots.txt honoured, "
                       "restricted/login-walled domains refused). Never marks jobs closed automatically "
                       "(results are always incomplete); use 'verify' on a job instead.")
    config_schema = {"urls": {"type": "array", "required": True}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        urls = cfg.get("urls")
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
            raise ConfigError("config.urls must be a non-empty list of URLs")
        for u in urls:
            check_url_policy(u)
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        res = ConnectorResult(complete=False)
        async with self.http() as http:
            robots = RobotsChecker(http)
            for u in cfg["urls"]:
                try:
                    raw, warns = await fetch_url_posting(http, robots, u)
                    res.jobs.append(raw)
                    res.warnings += warns
                except ConnectorError as e:
                    res.warnings.append(f"{u}: {e}")
        return res
