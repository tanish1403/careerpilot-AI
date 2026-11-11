from __future__ import annotations

from urllib.parse import quote

from .base import BaseConnector
from .errors import ConnectorError
from .interface import ConnectorResult, RawJob
from .normalize import (canonical_url, clean_description, extract_salary_text, infer_seniority,
                        infer_work_mode, parse_dt)


class AshbyConnector(BaseConnector):
    kind = "ashby"
    label = "Ashby job board"
    permitted_usage = ("Uses the public Ashby posting API (api.ashbyhq.com/posting-api/job-board/"
                       "{job_board_name}). Read-only, no authentication; unlisted postings are skipped. "
                       "Limitation: compensation is only present when the company publishes it.")
    config_schema = {"job_board_name": {"type": "string", "required": True},
                     "company_name": {"type": "string", "required": False}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        self.token(cfg, "job_board_name")
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        name = cfg["job_board_name"].strip()
        url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(name)}"
        async with self.http() as http:
            data = await http.get_json(url, params={"includeCompensation": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ConnectorError("Unexpected Ashby response shape")
        company = self.display_name(cfg, name)
        res = ConnectorResult()
        for e in data["jobs"]:
            try:
                if e.get("isListed") is False:
                    continue
                res.jobs.append(self._parse(e, company))
            except Exception as ex:  # noqa: BLE001
                res.complete = False
                res.warnings.append(f"skipped malformed job {e.get('id') if isinstance(e, dict) else '?'}: "
                                    f"{type(ex).__name__}")
        return res

    def _parse(self, e: dict, company: str) -> RawJob:
        url = e.get("jobUrl") or e["applyUrl"]
        loc = e.get("location")
        desc = clean_description(e.get("descriptionHtml") or e.get("descriptionPlain") or "")
        wt = (e.get("workplaceType") or "").lower()
        mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(wt) or \
            ("remote" if e.get("isRemote") else infer_work_mode(loc))
        comp = (e.get("compensation") or {}).get("compensationTierSummary")
        return RawJob(
            source_kind=self.kind, external_id=str(e["id"]), source_url=url,
            canonical_url=canonical_url(url), title=str(e["title"]).strip(), company=company,
            location=loc, work_mode=mode, description=desc,
            salary_text=comp or extract_salary_text(desc), seniority=infer_seniority(e["title"]),
            posted_at=parse_dt(e.get("publishedAt")), collection_method="public_api",
            raw={k: v for k, v in e.items() if k not in ("descriptionHtml", "descriptionPlain")})
