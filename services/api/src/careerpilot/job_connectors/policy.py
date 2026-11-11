"""Which URLs we will fetch at all. Login-walled / restricted platforms are refused with a
message that sends the user to apply at the source. Robots.txt is honoured everywhere."""
from __future__ import annotations

import ipaddress
import urllib.robotparser as robotparser
from urllib.parse import urlsplit

from .errors import BlockedError, RefusedSourceError
from .http import USER_AGENT, HttpFetcher

RESTRICTED_DOMAINS = {
    "linkedin.com": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter", "monster.com": "Monster", "facebook.com": "Facebook",
    "instagram.com": "Instagram", "twitter.com": "X/Twitter", "x.com": "X/Twitter",
    "wellfound.com": "Wellfound", "angel.co": "Wellfound", "dice.com": "Dice",
    "simplyhired.com": "SimplyHired",
}
ROBOTS_AGENT = "CareerPilotAI"


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def domain_allowed_by(host: str, allowed: list[str]) -> bool:
    host = host.lower()
    return any(host == d.lower().lstrip(".") or host.endswith("." + d.lower().lstrip("."))
               for d in allowed)


def check_url_policy(url: str) -> None:
    """Raises RefusedSourceError / BlockedError for URLs we never fetch."""
    p = urlsplit((url or "").strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedError("Only http(s) job URLs are supported.", url, code="invalid_url")
    host = p.hostname.lower()
    for dom, name in RESTRICTED_DOMAINS.items():
        if host == dom or host.endswith("." + dom):
            raise RefusedSourceError(
                f"{name} requires login or restricts automated access, so CareerPilot will not fetch "
                f"it. Open the posting yourself and apply at the source: {url}. You can paste the "
                "job description with 'Import text' to track and score it here.", url)
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise BlockedError("Local/internal addresses cannot be fetched.", url, code="invalid_url")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise BlockedError("Private network addresses cannot be fetched.", url, code="invalid_url")
    except ValueError:
        pass


class RobotsChecker:
    """RFC 9309 semantics: 4xx robots => allowed, 5xx/unreachable => disallowed, cached per origin."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher
        self._cache: dict[str, robotparser.RobotFileParser | bool] = {}

    async def allowed(self, url: str) -> bool:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._cache:
            self._cache[origin] = await self._load(origin)
        rp = self._cache[origin]
        if isinstance(rp, bool):
            return rp
        return rp.can_fetch(ROBOTS_AGENT, url) and rp.can_fetch(USER_AGENT, url)

    async def _load(self, origin: str):
        from .errors import ConnectorHTTPError
        try:
            resp = await self.fetcher.get(origin + "/robots.txt")
        except BlockedError:
            return True      # 4xx on robots.txt = no usable robots file (RFC 9309)
        except ConnectorHTTPError as e:
            return e.status in (404, 410)   # missing file => allowed; 5xx/network => disallow
        rp = robotparser.RobotFileParser()
        rp.parse(resp.text.splitlines())
        return rp
