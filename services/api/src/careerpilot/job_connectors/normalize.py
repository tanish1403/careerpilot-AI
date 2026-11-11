"""Canonical URLs, text cleaning, dedupe keys and cross-source similarity."""
from __future__ import annotations

import hashlib
import html as _html
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_PARAMS = {"gh_src", "lever-source", "lever-origin", "ref", "referrer", "source", "src", "fbclid",
                   "gclid", "msclkid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "trk", "trackingid",
                   "refid", "campaign", "cmpid", "icid", "igshid", "yclid", "mkt_tok", "li_fat_id",
                   "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
                   "ashby_jid_src", "s", "sid", "vero_id"}
_COMPANY_SUFFIX = {"inc", "incorporated", "llc", "ltd", "limited", "gmbh", "corp", "corporation", "co",
                   "plc", "sa", "ag", "bv", "pty", "company", "technologies", "technology", "labs"}
LEVEL_TOKENS = {"i", "ii", "iii", "iv", "v", "senior", "junior", "staff", "principal", "lead", "intern",
                "manager", "director", "head", "associate", "graduate", "vp", "frontend", "backend",
                "fullstack", "mobile", "data", "ml", "devops", "security", "qa", "sre"}
_TITLE_SUBS = [(r"\bsr\.?\b", "senior"), (r"\bjr\.?\b", "junior"), (r"&", " and "),
               (r"\bswe\b", "software engineer"), (r"\bfront[\s-]end\b", "frontend"),
               (r"\bback[\s-]end\b", "backend"), (r"\bfull[\s-]stack\b", "fullstack")]


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
               if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_"))
    path = re.sub(r"/{2,}", "/", p.path).rstrip("/") or ""
    return urlunsplit(((p.scheme or "https").lower(), host + port, path, urlencode(q), ""))


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#\s]", " ", s.lower())).strip()


def norm_company(name: str) -> str:
    toks = [t for t in _fold(name).split() if t not in _COMPANY_SUFFIX]
    return " ".join(toks)


def norm_title(title: str) -> str:
    t = (title or "").lower()
    for pat, rep in _TITLE_SUBS:
        t = re.sub(pat, rep, t)
    return _fold(t)


def norm_location(loc: str | None) -> str:
    return _fold(loc or "")


def url_key(canon: str) -> str:
    return sha("url:" + canon)


def cmp_key(company: str, title: str, location: str | None) -> str:
    return sha(f"cmp:{norm_company(company)}|{norm_title(title)}|{norm_location(location)}")


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def location_compatible(a: str | None, b: str | None) -> bool:
    ta, tb = set(norm_location(a).split()), set(norm_location(b).split())
    if not ta or not tb:
        return True
    return ta <= tb or tb <= ta or jaccard(ta, tb) >= 0.6


def title_similarity(a: str, b: str) -> float:
    na, nb = norm_title(a), norm_title(b)
    ta, tb = set(na.split()), set(nb.split())
    if {t for t in ta if t in LEVEL_TOKENS or t.isdigit()} != {t for t in tb if t in LEVEL_TOKENS or t.isdigit()}:
        return 0.0
    return max(jaccard(ta, tb), SequenceMatcher(None, na, nb).ratio())


def probable_duplicate(a_title: str, a_loc: str | None, b_title: str, b_loc: str | None) -> bool:
    """Same company assumed by caller. Title similarity + compatible location."""
    return title_similarity(a_title, b_title) >= 0.85 and location_compatible(a_loc, b_loc)


# ---- text -------------------------------------------------------------------
_ZW = re.compile("[​‌‍⁠﻿]")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
MAX_DESC = 100_000


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    if "&lt;" in raw and not _TAG.search(raw):   # entity-escaped HTML (Greenhouse content)
        raw = _html.unescape(raw)
    if not _TAG.search(raw):
        return clean_text(_html.unescape(raw))
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "noscript", "template", "iframe", "svg"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
        li.append("\n")
    for t in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "section"]):
        t.insert_before("\n")
        t.append("\n")
    return clean_text(soup.get_text())


def clean_text(text: str) -> str:
    text = _ZW.sub("", text or "").replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    keep = [ln for i, ln in enumerate(out)
            if not (ln == "" and 0 < i < len(out) - 1 and out[i - 1].startswith("- ")
                    and out[i + 1].startswith("- "))]
    return "\n".join(keep).strip()[:MAX_DESC]


def clean_description(raw: str) -> str:
    return html_to_text(raw)


# ---- misc extraction --------------------------------------------------------
def parse_dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
        s = str(v).strip().replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def infer_work_mode(*texts: str | None) -> str:
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh|telecommut|anywhere)\b", t):
        return "remote"
    if re.search(r"\b(on[\s-]?site|in[\s-]office|in[\s-]person)\b", t):
        return "onsite"
    return "unknown"


_SENIORITY = [("intern", r"\b(intern|internship|working student)\b"),
              ("director", r"\b(director|head of|vp|vice president)\b"),
              ("manager", r"\bmanager\b"),
              ("principal", r"\bprincipal\b"), ("staff", r"\bstaff\b"),
              ("lead", r"\b(lead|tech lead)\b"),
              ("senior", r"\b(senior|sr\.?)\b"),
              ("junior", r"\b(junior|jr\.?|entry[\s-]level|graduate|new grad|associate)\b")]


def infer_seniority(title: str) -> str | None:
    t = (title or "").lower()
    for name, pat in _SENIORITY:
        if re.search(pat, t):
            return name
    return None


_SAL = re.compile(r"((?:USD|EUR|GBP|CAD|AUD|INR|\$|€|£)\s?\d[\d,.]*\s?[kK]?(?:\s?(?:-|–|—|to)\s?(?:USD|EUR|GBP|\$|€|£)?\s?\d[\d,.]*\s?[kK]?)?"
                  r"(?:\s?(?:per|/)\s?(?:year|yr|annum|hour|hr|month))?)")


def extract_salary_text(text: str) -> str | None:
    for m in _SAL.finditer(text or ""):
        s = m.group(1).strip()
        if sum(c.isdigit() for c in s) >= 4:
            return s[:200]
    return None


def parse_salary_range(text: str | None) -> tuple[float, float] | None:
    """Best-effort annualised (min, max) from free text; None when unparseable."""
    if not text:
        return None
    nums = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s?([kK])?", text):
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            n *= 1000
        nums.append(n)
    nums = [n for n in nums if n >= 10]
    if not nums:
        return None
    lo, hi = min(nums[:2]), max(nums[:2])
    if re.search(r"hour|/\s?hr", text, re.I):
        lo, hi = lo * 2080, hi * 2080
    elif re.search(r"month", text, re.I):
        lo, hi = lo * 12, hi * 12
    return lo, hi
