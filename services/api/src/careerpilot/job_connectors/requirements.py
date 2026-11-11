"""Heuristic requirement extraction: mandatory vs preferred, normalized against the skill taxonomy."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..matching.taxonomy import find_skills

MAX_ROWS = 60
_REQ_H = {"requirements", "requirement", "qualifications", "minimum qualifications", "basic qualifications",
          "required qualifications", "required skills", "required", "must haves", "must have",
          "what you ll need", "what you need", "what we re looking for", "who you are", "you have",
          "about you", "your profile", "what you bring", "skills and experience", "skills experience",
          "key requirements", "skills", "experience", "you should have", "what you ll bring", "the ideal candidate"}
_PREF_H = {"nice to have", "nice to haves", "preferred", "preferred qualifications", "preferred skills",
           "bonus", "bonus points", "desired", "desired skills", "good to have", "pluses", "a plus",
           "extra credit", "it s a plus", "ideally", "nice to haves bonus"}
_RESP_H = {"responsibilities", "what you ll do", "the role", "your role", "day to day", "duties",
           "what you will do", "key responsibilities", "in this role you will", "about the role"}
_OTHER_H = {"about us", "about the company", "benefits", "perks", "compensation", "our culture", "how to apply",
            "equal opportunity", "why join us", "what we offer", "our values", "the team", "our stack",
            "salary", "life at"}
_PREF_CUE = re.compile(r"\b(preferred|nice to have|a plus|bonus|ideally|desirable|familiarity|exposure to|"
                       r"is a plus|are a plus|advantage|good to have)\b", re.I)
_MAND_CUE = re.compile(r"\b(required|must|minimum|need to|needs to|essential|mandatory|legally|eligible)\b", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|-\s*\d{1,2}|to\s*\d{1,2})?\s*(?:years?|yrs?)\b", re.I)
_DEGREE = re.compile(r"\b(ph\.?d|doctorate|master'?s?|m\.?s\.?c?|mba|bachelor'?s?|b\.?s\.?c?|b\.?a\.?|b\.?eng|"
                     r"b\.?tech|associate'?s?|undergraduate|university degree|college degree|degree)\b", re.I)
_AUTH = re.compile(r"(work authori[sz]ation|authori[sz]ed to work|right to work|legally (?:able|authori[sz]ed)|"
                   r"eligib\w+ to work|visa|sponsorship|security clearance|clearance|citizen)", re.I)
_LOC = re.compile(r"(must be (?:located|based)|required to (?:be )?(?:located|based)|(?:located|based|reside) in|"
                  r"on-?site (?:in|at)|relocat\w+|within commuting distance)", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•▪◦‣·]|\d{1,2}[.)])\s+")
_DEG_RANK = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}


@dataclass
class ReqItem:
    text: str
    kind: str
    mandatory: bool
    normalized: str | None


def _norm_heading(line: str) -> str:
    h = re.sub(r"\(.*?\)", " ", line.lower())
    h = re.sub(r"[^a-z0-9 ]+", " ", h.replace("'", " "))
    return re.sub(r"\s+", " ", h).strip()


def _heading_kind(line: str) -> str | None:
    if _BULLET.match(line) or len(line) > 60 or line.endswith("."):
        return None
    h = _norm_heading(line)
    if h in _PREF_H:
        return "preferred"
    if h in _REQ_H:
        return "required"
    if h in _RESP_H:
        return "responsibilities"
    if h in _OTHER_H:
        return "other"
    return None


def degree_level(text: str) -> str | None:
    t = text.lower()
    found = []
    if re.search(r"ph\.?d|doctorate", t):
        found.append("phd")
    if re.search(r"\bmaster|\bm\.?sc?\b|\bmba\b", t):
        found.append("master")
    if re.search(r"\bbachelor|\bb\.?(?:s|a|sc|eng|tech)\b|undergraduate|university degree|college degree", t):
        found.append("bachelor")
    if re.search(r"\bassociate", t):
        found.append("associate")
    if not found and re.search(r"\bdegree\b", t):
        found.append("bachelor")
    return min(found, key=lambda d: _DEG_RANK[d]) if found else None


def _classify(line: str, mandatory: bool) -> list[ReqItem]:
    items: list[ReqItem] = []
    text = line.strip()
    if _PREF_CUE.search(text):
        mandatory = False
    elif _MAND_CUE.search(text):
        mandatory = True
    ym = _YEARS.search(text)
    if ym and not re.search(r"\b(funded|founded|old|ago)\b", text, re.I):
        items.append(ReqItem(text, "experience", mandatory, f"experience_years:{int(ym.group(1))}"))
    lvl = degree_level(text) if _DEGREE.search(text) else None
    if lvl:
        items.append(ReqItem(text, "education", mandatory, f"degree:{lvl}"))
    if _AUTH.search(text):
        low = text.lower()
        norm = ("authorization:clearance" if "clearance" in low else
                "authorization:no_sponsorship" if re.search(r"(no|not|unable to|without).{0,30}sponsor|sponsorship.{0,20}(not|unavailable)", low)
                else "authorization:work_authorization")
        items.append(ReqItem(text, "authorization", True if _MAND_CUE.search(text) or mandatory else False, norm))
    if _LOC.search(text):
        m = re.search(r"(?:located|based|reside|on-?site)\s+(?:in|at)\s+([A-Z][\w .,'-]{1,50}?)(?:[.;]|\bor\b|\band\b|$)", text)
        place = m.group(1).strip(" ,").lower() if m else ""
        items.append(ReqItem(text, "location", mandatory, f"location:{place}" if place else "location:onsite"))
    for sk in find_skills(text):
        items.append(ReqItem(text, "skill", mandatory, sk))
    return items


def extract_requirements(description: str, explicit: list[str] | None = None) -> list[ReqItem]:
    out: list[ReqItem] = []
    section: str | None = None
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hk = _heading_kind(line.rstrip(":"))
        if hk:
            section = hk
            continue
        bullet = bool(_BULLET.match(line))
        body = _BULLET.sub("", line).strip()
        if len(body) < 3 or len(body) > 400:
            continue
        if section in ("required", "preferred"):
            got = _classify(body, mandatory=(section == "required"))
            if not got and (bullet or len(body) <= 160):
                strong = bool(_MAND_CUE.search(body)) and section == "required"
                got = [ReqItem(body, "other", strong, None)]
            out += got
        elif section in ("responsibilities", "other"):
            continue
        else:   # no section: only sentences with explicit hard cues
            if _YEARS.search(body) or _AUTH.search(body) or _DEGREE.search(body) or _LOC.search(body):
                for s in re.split(r"(?<=[.!?])\s+", body):
                    out += [i for i in _classify(s, mandatory=False) if i.kind != "skill"]
    for e in explicit or []:
        out += _classify(e, True) or [ReqItem(e.strip(), "other", False, None)]
    seen: set[tuple] = set()
    uniq: list[ReqItem] = []
    for i in out:
        key = (i.kind, i.normalized or i.text.lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(i)
    return uniq[:MAX_ROWS]
