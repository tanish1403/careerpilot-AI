"""OPTIONAL, DISABLED-BY-DEFAULT JobSpy adapter (stub).

JobSpy scrapes third-party job portals. That needs a licence, maintenance and per-site Terms-of-Service
review before use, so it raises unless the source config explicitly enables it AND the package is
installed. Sites that forbid or technically block scraping (LinkedIn etc.) are always refused."""
from __future__ import annotations

import asyncio
import hashlib

from .base import BaseConnector
from .errors import ConfigError, ConnectorDisabled
from .interface import ConnectorResult, RawJob
from .normalize import canonical_url, clean_description, infer_seniority, infer_work_mode, parse_dt

FORBIDDEN_SITES = {"linkedin", "glassdoor", "indeed", "ziprecruiter"}
REVIEW_MSG = ("The JobSpy adapter requires licence and site Terms-of-Service review before use and is "
              "disabled by default. To enable it deliberately set config.enabled=true and "
              "config.tos_reviewed=true on this source and install the 'python-jobspy' package.")


class JobSpyConnector(BaseConnector):
    kind = "jobspy"
    label = "JobSpy (optional, disabled by default)"
    permitted_usage = ("Disabled by default. Requires explicit enablement after licence/ToS review and "
                       "the optional python-jobspy package. Never used for LinkedIn or other sites that "
                       "restrict automated access. Results are never treated as complete.")
    config_schema = {"enabled": {"type": "boolean", "default": False},
                     "tos_reviewed": {"type": "boolean", "default": False},
                     "search_term": {"type": "string"}, "location": {"type": "string"},
                     "sites": {"type": "array"}, "results_wanted": {"type": "integer", "default": 20}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        bad = FORBIDDEN_SITES & {str(s).lower() for s in cfg.get("sites") or []}
        if bad:
            raise ConfigError(f"Sites not permitted for automated collection: {', '.join(sorted(bad))}")
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        if not (cfg.get("enabled") is True and cfg.get("tos_reviewed") is True):
            raise ConnectorDisabled(REVIEW_MSG)
        try:
            import jobspy  # type: ignore
        except ImportError as e:
            raise ConnectorDisabled("python-jobspy is not installed. " + REVIEW_MSG) from e
        kw = {"search_term": cfg.get("search_term") or "software engineer",
              "location": cfg.get("location"), "site_name": cfg.get("sites") or ["google"],
              "results_wanted": int(cfg.get("results_wanted") or 20)}
        df = await asyncio.to_thread(jobspy.scrape_jobs, **kw)
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
        res = ConnectorResult(complete=False, warnings=["JobSpy results are never treated as complete"])
        for r in rows:
            url = str(r.get("job_url") or "")
            if not url or not r.get("title"):
                continue
            title = str(r["title"])
            res.jobs.append(RawJob(
                source_kind=self.kind, external_id=str(r.get("id") or hashlib.sha1(url.encode()).hexdigest()[:16]),
                source_url=url, canonical_url=canonical_url(url), title=title,
                company=str(r.get("company") or "Unknown company"),
                location=str(r["location"]) if r.get("location") else None,
                work_mode="remote" if r.get("is_remote") else infer_work_mode(str(r.get("location") or "")),
                description=clean_description(str(r.get("description") or "")),
                seniority=infer_seniority(title), posted_at=parse_dt(r.get("date_posted")),
                collection_method="jobspy", raw={k: str(v) for k, v in r.items() if k != "description"}))
        return res
