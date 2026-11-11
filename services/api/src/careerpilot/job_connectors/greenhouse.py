from __future__ import annotations

from urllib.parse import quote

from .base import BaseConnector
from .errors import ConnectorError
from .interface import ConnectorResult, RawJob
from .normalize import (canonical_url, clean_description, extract_salary_text, infer_seniority,
                        infer_work_mode, parse_dt)


class GreenhouseConnector(BaseConnector):
    kind = "greenhouse"
    label = "Greenhouse job board"
    permitted_usage = ("Uses the public Greenhouse Job Board API (boards-api.greenhouse.io/v1/boards/"
                       "{board_token}/jobs?content=true). Read-only, no authentication. Only boards "
                       "that publish openly; rate limited per source. Limitation: the API has no "
                       "company name field (set config.company_name) and posting dates may be absent.")
    config_schema = {"board_token": {"type": "string", "required": True},
                     "company_name": {"type": "string", "required": False}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        self.token(cfg, "board_token")
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        tok = cfg["board_token"].strip()
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(tok)}/jobs"
        async with self.http() as http:
            data = await http.get_json(url, params={"content": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ConnectorError("Unexpected Greenhouse response shape")
        company = self.display_name(cfg, tok)
        res = ConnectorResult()
        for e in data["jobs"]:
            try:
                res.jobs.append(self._parse(e, company))
            except Exception as ex:  # noqa: BLE001
                res.complete = False
                res.warnings.append(f"skipped malformed job {e.get('id') if isinstance(e, dict) else '?'}: "
                                    f"{type(ex).__name__}")
        total = (data.get("meta") or {}).get("total")
        if isinstance(total, int) and total > len(data["jobs"]):
            res.complete = False
            res.warnings.append(f"board reports {total} jobs but only {len(data['jobs'])} returned")
        return res

    def _parse(self, e: dict, company: str) -> RawJob:
        title = str(e["title"]).strip()
        url = e["absolute_url"]
        loc = (e.get("location") or {}).get("name")
        desc = clean_description(e.get("content") or "")
        salary = None
        ranges = e.get("pay_input_ranges")
        if isinstance(ranges, list) and ranges:
            r = ranges[0]
            if r.get("min_cents") is not None and r.get("max_cents") is not None:
                salary = f"{r.get('currency_type', '')} {r['min_cents'] // 100}-{r['max_cents'] // 100} per year".strip()
        return RawJob(
            source_kind=self.kind, external_id=str(e["id"]), source_url=url,
            canonical_url=canonical_url(url), title=title, company=company, location=loc,
            work_mode=infer_work_mode(loc, title), description=desc,
            salary_text=salary or extract_salary_text(desc), seniority=infer_seniority(title),
            posted_at=parse_dt(e.get("first_published")), collection_method="public_api",
            raw={k: v for k, v in e.items() if k != "content"} | {"content_chars": len(e.get("content") or "")})
