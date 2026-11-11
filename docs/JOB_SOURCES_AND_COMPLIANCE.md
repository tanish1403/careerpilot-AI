# Job sources and compliance

Status: connectors are **experimental**; verified only against mocked HTTP and fixtures, never live boards.

| Kind | Notes |
|---|---|
| Greenhouse, Lever, Ashby | Public board endpoints for a company slug the user supplies |
| Career page | Generic extraction from a user-supplied page |
| URL import / text import | User-initiated, one job at a time; manual records never auto-close |
| jobspy (optional) | Adapter present; not installed or tested here |

Policy (`job_connectors/policy.py`): only http(s); robots.txt honoured (agent `CareerPilotAI`); refused platforms:
LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster, Facebook, Instagram, X/Twitter, Wellfound/AngelList, Dice,
SimplyHired (response tells the user to apply at the source, `code: refused_domain`); login walls refused.
Per-source rate limit; jobs keep source, URL, first-seen and last-verified; a job closes only when every source
record is absent from a complete listing. Private/loopback targets are checked in the policy layer.

Users remain responsible for each site's terms of service. This document is not legal advice.
