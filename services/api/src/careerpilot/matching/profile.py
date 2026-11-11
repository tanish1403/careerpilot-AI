"""Read-only snapshot of the candidate profile for matching. Only CONFIRMED facts are evidence."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from ..db.models import (CandidateProfile, Education, Experience, Project, ProfileFact, Skill)
from ..job_connectors.requirements import degree_level
from .taxonomy import canonical_skill, find_domains, find_skills, role_families

_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                             "oct", "nov", "dec"])}


def ev(type_: str, id_: str, label: str, confirmed: bool) -> dict:
    return {"type": type_, "id": id_, "label": label, "status": "confirmed" if confirmed else "unconfirmed"}


def as_list(v) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;\n]", v) if x.strip()]
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v)]


def parse_ym(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    t = str(s).strip().lower()
    if t in ("present", "current", "now", "ongoing"):
        today = date.today()
        return today.year, today.month
    m = re.search(r"(19|20)\d{2}", t)
    if not m:
        return None
    y = int(m.group(0))
    mm = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", t)
    if mm:
        return y, _MONTHS[mm.group(1)]
    m2 = re.search(r"(?:^|\D)(0?[1-9]|1[0-2])[-/.]((?:19|20)\d{2})|((?:19|20)\d{2})[-/.](0?[1-9]|1[0-2])", t)
    if m2:
        return (int(m2.group(2)), int(m2.group(1))) if m2.group(1) else (int(m2.group(3)), int(m2.group(4)))
    return y, 1


@dataclass
class Item:
    id: str
    type: str
    label: str
    confirmed: bool
    text: str = ""
    extra: dict = field(default_factory=dict)

    def ev(self) -> dict:
        return ev(self.type, self.id, self.label, self.confirmed)


@dataclass
class ProfileSnapshot:
    profile_id: str
    version: int
    location: str
    headline: str
    summary: str
    preferences: dict
    skills: list[Item]
    experiences: list[Item]
    education: list[Item]
    projects: list[Item]
    hash: str = ""

    @property
    def confirmed_skill_names(self) -> dict[str, Item]:
        return {canonical_skill(s.label): s for s in self.skills if s.confirmed}

    @property
    def unconfirmed_skill_names(self) -> dict[str, Item]:
        return {canonical_skill(s.label): s for s in self.skills if not s.confirmed}

    def confirmed(self, items: list[Item]) -> list[Item]:
        return [i for i in items if i.confirmed]

    def experience_years(self) -> float | None:
        """Union of confirmed experience date ranges, in years; None when no confirmed dated experience."""
        spans = []
        for e in self.experiences:
            if not e.confirmed:
                continue
            a, b = parse_ym(e.extra.get("start")), parse_ym(e.extra.get("end") or "present")
            if a and b and (b[0] * 12 + b[1]) >= (a[0] * 12 + a[1]):
                spans.append((a[0] * 12 + a[1], b[0] * 12 + b[1]))
        if not spans:
            return None
        spans.sort()
        total, cur_s, cur_e = 0, spans[0][0], spans[0][1]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                total += cur_e - cur_s
                cur_s, cur_e = s, e
        total += cur_e - cur_s
        return round(total / 12, 2)

    def best_degree(self) -> tuple[str | None, Item | None]:
        rank = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}
        best: tuple[str | None, Item | None] = (None, None)
        for e in self.education:
            if e.confirmed:
                lvl = degree_level(e.extra.get("degree") or "")
                if lvl and (best[0] is None or rank[lvl] > rank[best[0]]):
                    best = (lvl, e)
        return best

    def has_confirmed_education(self) -> bool:
        return any(e.confirmed for e in self.education)

    def text_domains(self) -> dict[str, list[Item]]:
        out: dict[str, list[Item]] = {}
        for it in self.experiences + self.projects:
            if it.confirmed:
                for d in find_domains(it.text):
                    out.setdefault(d, []).append(it)
        return out

    def skill_evidence(self, skill: str) -> tuple[float, dict | None]:
        """(credit, evidence). 1.0 confirmed skill, 0.7 shown in confirmed project/experience text,
        0.0 otherwise (unconfirmed items are NOT evidence)."""
        s = self.confirmed_skill_names.get(skill)
        if s:
            return 1.0, s.ev()
        for it in self.projects + self.experiences:
            if it.confirmed and skill in find_skills(it.text + " " + " ".join(it.extra.get("tech", []))):
                return 0.7, it.ev()
        return 0.0, None


def _confirmed(item_status: str | None, fact: ProfileFact | None) -> bool:
    return item_status == "confirmed" and (fact is None or fact.status == "confirmed")


def load_profile(db: Session) -> ProfileSnapshot | None:
    p = (db.query(CandidateProfile).filter(CandidateProfile.deleted_at.is_(None))
         .order_by(CandidateProfile.created_at.desc()).first())
    if p is None:
        return None
    facts = {f.id: f for f in db.query(ProfileFact).filter(ProfileFact.profile_id == p.id,
                                                           ProfileFact.deleted_at.is_(None)).all()}
    q = lambda M: db.query(M).filter(M.profile_id == p.id, M.deleted_at.is_(None)).all()  # noqa: E731
    skills: list[Item] = []
    used_facts: set[str] = set()
    for s in q(Skill):
        f = facts.get(s.fact_id) if s.fact_id else None
        if s.fact_id:
            used_facts.add(s.fact_id)
        if s.status == "rejected" or (f is not None and f.status == "rejected"):
            continue
        skills.append(Item(s.fact_id or s.id, "skill", s.name, _confirmed(s.status, f),
                           extra={"years": s.years}))
    for f in facts.values():
        if f.category == "skill" and f.id not in used_facts and f.status != "rejected":
            name = (f.value or {}).get("name") or f.key
            skills.append(Item(f.id, "skill", str(name), f.status == "confirmed"))
    exps = []
    for e in q(Experience):
        f = facts.get(e.fact_id) if e.fact_id else None
        if e.status == "rejected":
            continue
        exps.append(Item(e.fact_id or e.id, "experience", f"{e.title} at {e.company}", _confirmed(e.status, f),
                         text=" ".join([e.title, e.company or ""] + [str(b) for b in e.bullets or []]),
                         extra={"start": e.start_date, "end": e.end_date, "title": e.title}))
    edus = []
    for e in q(Education):
        f = facts.get(e.fact_id) if e.fact_id else None
        if e.status == "rejected":
            continue
        edus.append(Item(e.fact_id or e.id, "education", f"{e.degree or ''} {e.field or ''} {e.institution}".strip(),
                         _confirmed(e.status, f), extra={"degree": " ".join([e.degree or "", e.field or ""])}))
    projs = []
    for pr in q(Project):
        f = facts.get(pr.fact_id) if pr.fact_id else None
        if pr.status == "rejected":
            continue
        tech = [str(t) for t in pr.technologies or []]
        projs.append(Item(pr.fact_id or pr.id, "project", pr.name, _confirmed(pr.status, f),
                          text=" ".join([pr.name, pr.description or ""] + [str(b) for b in pr.bullets or []] + tech),
                          extra={"tech": tech}))
    snap = ProfileSnapshot(p.id, p.version or 1, p.location or "", p.headline or "", p.summary or "",
                           dict(p.preferences or {}), skills, exps, edus, projs)
    blob = json.dumps({"v": snap.version, "loc": snap.location, "h": snap.headline, "prefs": snap.preferences,
                       "items": sorted((i.type, i.id, i.label, i.confirmed, i.text, str(sorted(i.extra.items(), key=str)))
                                       for i in skills + exps + edus + projs)}, sort_keys=True, default=str)
    snap.hash = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return snap


def title_roles(text: str) -> list[str]:
    return role_families(text)
