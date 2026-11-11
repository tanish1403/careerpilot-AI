"""Per-ATS adapters targeting the public application page structure of each vendor.
Selectors are best-effort scoping hints only; field location is always label/role first."""
from __future__ import annotations

from ..allowlist import host_of
from .base import GenericFormAdapter


class _HostAdapter(GenericFormAdapter):
    def detect(self, url: str) -> bool:
        h = host_of(url) or ""
        return any(h == x or h.endswith("." + x) for x in self.hosts)


class GreenhouseAdapter(_HostAdapter):
    name = "greenhouse"
    hosts = ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io")
    description = "Greenhouse hosted job boards (public application form)."
    form_selectors = ("form#application_form", "form#application-form", "form[action*='applications']")
    name_hints = {"first_name": "First Name", "last_name": "Last Name", "email": "Email",
                  "phone": "Phone", "resume": "Resume/CV", "cover_letter": "Cover Letter"}


class LeverAdapter(_HostAdapter):
    name = "lever"
    hosts = ("jobs.lever.co", "jobs.eu.lever.co")
    description = "Lever hosted postings (public /apply form)."
    form_selectors = ("form#application-form", "form.application-form",
                      ".application-page form", "form[action*='/apply']")
    name_hints = {"name": "Full name", "email": "Email", "phone": "Phone", "org": "Current company",
                  "urls[LinkedIn]": "LinkedIn URL", "urls[GitHub]": "GitHub URL",
                  "urls[Portfolio]": "Portfolio URL", "resume": "Resume/CV",
                  "comments": "Additional information"}


class AshbyAdapter(_HostAdapter):
    name = "ashby"
    hosts = ("jobs.ashbyhq.com",)
    description = "Ashby hosted job boards (public application form)."
    form_selectors = ("form[class*='ashby-application-form']", "[class*='ashby-application-form'] form",
                      "form[class*='application']")
    name_hints = {"_systemfield_name": "Name", "_systemfield_email": "Email",
                  "_systemfield_phone": "Phone", "_systemfield_resume": "Resume"}
