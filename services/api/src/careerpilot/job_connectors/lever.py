from __future__ import annotations

from urllib.parse import quote

from .base import BaseConnector
from .errors import ConnectorError, ConnectorHTTPError
from .interface import ConnectorResult, RawJob
from .normalize import (canonical_url, clean_description, extract_salary_text, infer_seniority,
                        infer_work_mode, parse_dt)

PAGE = 100
MAX_PAGES = 50


class LeverConnector(BaseConnector):
    kind = "lever"
    label = "Lever postings"
    permitted_usage = ("Uses the public Lever Postings API (api.lever.co/v0/postings/{company}?mode=json), "
                       "paginated with skip/limit. Read-only, no authentication. Limitation: if a later "
                       "page fails, the result is marked incomplete and no job is closed because of it.")
    config_schema = {"company": {"type": "string", "required": True},
                     "company_name": {"type": "string", "required": False}}

    def validate_config(self, config: dict) -> dict:
        cfg = dict(config or {})
        self.token(cfg, "company")
        return cfg

    async def fetch(self, config: dict) -> ConnectorResult:
        cfg = self.validate_config(config)
        slug = cfg["company"].strip()
        url = f"https://api.lever.co/v0/postings/{quote(slug)}"
        company = self.display_name(cfg, slug)
        res = ConnectorResult()
        async with self.http() as http:
            skip = 0
            for page in range(MAX_PAGES):
                try:
                    data = await http.get_json(url, params={"mode": "json", "skip": skip, "limit": PAGE})
                except ConnectorHTTPError as e:
                    if page == 0:
                        raise
                    res.complete = False
                    res.warnings.append(f"page {page + 1} failed ({e}); result is partial")
                    break
                if not isinstance(data, list):
                    if page == 0:
                        raise ConnectorError("Unexpected Lever response shape")
                    res.complete = False
                    res.warnings.append(f"page {page + 1} had an unexpected shape")
                    break
                for e in data:
                    try:
                        res.jobs.append(self._parse(e, company))
                    except Exception as ex:  # noqa: BLE001
                        res.complete = False
                        res.warnings.append(f"skipped malformed posting {e.get('id') if isinstance(e, dict) else '?'}: "
                                            f"{type(ex).__name__}")
                if len(data) < PAGE:
                    break
                skip += PAGE
            else:
                res.complete = False
                res.warnings.append(f"stopped after {MAX_PAGES} pages")
        return res

    def _parse(self, e: dict, company: str) -> RawJob:
        cats = e.get("categories") or {}
        loc = cats.get("location") or "; ".join(cats.get("allLocations") or []) or None
        parts = [e.get("descriptionPlain") or clean_description(e.get("description") or "")]
        for lst in e.get("lists") or []:
            parts.append(f"{lst.get('text', '')}:\n{clean_description(lst.get('content') or '')}")
        parts.append(e.get("additionalPlain") or clean_description(e.get("additional") or ""))
        desc = "\n\n".join(p for p in parts if p).strip()
        wt = (e.get("workplaceType") or "").lower()
        mode = wt if wt in ("remote", "hybrid", "onsite") else \
            ("onsite" if wt == "on-site" else infer_work_mode(loc))
        sal = e.get("salaryDescriptionPlain") or e.get("salaryDescription")
        sr = e.get("salaryRange")
        if not sal and isinstance(sr, dict) and sr.get("min") is not None:
            sal = f"{sr.get('currency', '')} {sr['min']}-{sr.get('max')} {sr.get('interval', '')}".strip()
        url = e.get("hostedUrl") or e["applyUrl"]
        return RawJob(
            source_kind=self.kind, external_id=str(e["id"]), source_url=url,
            canonical_url=canonical_url(url), title=str(e["text"]).strip(), company=company,
            location=loc, work_mode=mode, description=desc,
            salary_text=sal or extract_salary_text(desc), seniority=infer_seniority(e["text"]),
            posted_at=parse_dt(e.get("createdAt")), collection_method="public_api",
            raw={k: v for k, v in e.items() if k not in ("description", "descriptionPlain", "lists",
                                                         "additional", "additionalPlain")})
