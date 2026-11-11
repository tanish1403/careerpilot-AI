"""Domain allowlist. Enforced before navigation and on every redirect hop (see session.py)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com")
SETTING_KEY = "automation.allowlist"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?$")


def host_of(url: str) -> str | None:
    try:
        h = urlparse(url).hostname
    except ValueError:
        return None
    return h.lower().rstrip(".") if h else None


def normalize_entry(entry: str) -> str:
    """Validate a hostname entry (no scheme/path/port/wildcards)."""
    e = (entry or "").strip().lower().rstrip(".")
    if not _HOST.match(e) or "*" in e:
        raise ValueError(f"invalid allowlist host: {entry!r}")
    return e


def is_allowed(url: str, allowlist: list[str] | tuple[str, ...] | set[str]) -> bool:
    """True only for http(s) URLs whose exact hostname is allowlisted; plain http only on loopback."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = host_of(url)
    if not host or p.scheme not in ("http", "https"):
        return False
    if p.scheme == "http" and host not in LOOPBACK:
        return False
    return host in {a.lower() for a in allowlist}


def get_allowlist(db) -> list[str]:  # noqa: ANN001
    from ..db.models import Setting
    row = db.get(Setting, SETTING_KEY)
    if row is None or not isinstance(row.value, list):
        return list(DEFAULT_ALLOWLIST)
    return [str(x).lower() for x in row.value]


def set_allowlist(db, hosts: list[str]) -> list[str]:  # noqa: ANN001
    from ..db.models import Setting
    clean = sorted({normalize_entry(h) for h in hosts})
    row = db.get(Setting, SETTING_KEY)
    if row:
        row.value = clean
    else:
        db.add(Setting(key=SETTING_KEY, value=clean))
    db.flush()
    return clean
