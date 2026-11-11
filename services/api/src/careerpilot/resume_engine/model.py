"""Resume content model assembled ONLY from confirmed ProfileFacts."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..db.models import CandidateProfile
from ..documents import profile_service as ps
from ..documents.dates import format_date, month_index, parse_ym


@dataclass
class Bullet:
    text: str
    evidence_ids: list[str]
    source_text: str = ""        # the confirmed text this bullet came from
    reworded: bool = False


@dataclass
class Entry:
    kind: str                    # experience|education|project|publication|certification
    fact_id: str
    title: str
    org: str = ""
    dates: str = ""
    location: str = ""
    url: str = ""
    bullets: list[Bullet] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)


@dataclass
class SkillGroup:
    category: str
    names: list[str]
    fact_ids: list[str]


@dataclass
class ResumeModel:
    name: str
    contact: dict
    summary: tuple[str, str] | None
    experiences: list[Entry]
    education: list[Entry]
    projects: list[Entry]
    publications: list[Entry]
    certifications: list[Entry]
    skill_groups: list[SkillGroup]
    profile_version: int
    fact_ids: set[str] = field(default_factory=set)

    def entries(self) -> list[Entry]:
        return (self.experiences + self.education + self.projects + self.publications
                + self.certifications)

    def is_empty(self) -> bool:
        return not (self.experiences or self.education or self.projects or self.skill_groups
                    or self.publications or self.certifications)


def _range_text(s: str | None, e: str | None) -> str:
    a, b = format_date(s), format_date(e)
    if a and b:
        return f"{a} – {b}"
    return a or b


def _sort_key(v: dict) -> tuple[int, int]:
    s = parse_ym(v.get("start_date"), end=False)
    e = parse_ym(v.get("end_date"), end=True) if v.get("end_date") else None
    if e is None and s is not None:
        e = parse_ym("Present")
    return (month_index(e) if e else -1, month_index(s) if s else -1)


def build_model(db: Session, profile: CandidateProfile) -> ResumeModel:
    facts = ps.confirmed_facts(db, profile)   # status == 'confirmed' only
    by: dict[str, list] = {}
    for f in facts:
        by.setdefault(f.category, []).append(f)
    m = ResumeModel(
        name=profile.full_name or "", profile_version=profile.version,
        contact={k: v for k, v in {
            "email": profile.email, "phone": profile.phone, "location": profile.location,
            "headline": profile.headline, "links": profile.links or {}}.items() if v},
        summary=None, experiences=[], education=[], projects=[], publications=[],
        certifications=[], skill_groups=[])
    summ = by.get("summary", [])
    if summ:
        latest = max(summ, key=lambda f: (f.updated_at, f.id))
        if latest.value.get("text"):
            m.summary = (latest.value["text"], latest.id)
    for f in sorted(by.get("experience", []), key=lambda f: _sort_key(f.value), reverse=True):
        v = f.value
        m.experiences.append(Entry(
            "experience", f.id, v.get("title") or "", v.get("company") or "",
            _range_text(v.get("start_date"), v.get("end_date")), v.get("location") or "",
            bullets=[Bullet(b, [f.id], b) for b in v.get("bullets", [])]))
    for f in sorted(by.get("education", []), key=lambda f: _sort_key(f.value), reverse=True):
        v = f.value
        degree = " ".join(x for x in (v.get("degree"),) if x)
        if v.get("field") and degree:
            degree += f", {v['field']}"
        elif v.get("field"):
            degree = v["field"]
        title, org = (degree, v.get("institution") or "") if degree else \
            (v.get("institution") or "", "")
        m.education.append(Entry(
            "education", f.id, title, org, _range_text(v.get("start_date"), v.get("end_date")),
            f"GPA {v['grade']}" if v.get("grade") else ""))
    for f in by.get("project", []):
        v = f.value
        bl = v.get("bullets") or ([v["description"]] if v.get("description") else [])
        m.projects.append(Entry("project", f.id, v.get("name") or "",
                                ", ".join(v.get("technologies") or []), "", "",
                                url=v.get("url") or "", technologies=v.get("technologies") or [],
                                bullets=[Bullet(b, [f.id], b) for b in bl]))
    for f in sorted(by.get("publication", []), key=lambda f: f.value.get("year") or "",
                    reverse=True):
        v = f.value
        m.publications.append(Entry("publication", f.id, v.get("title") or "",
                                    v.get("venue") or "", v.get("year") or "", "",
                                    url=v.get("url") or ""))
    for f in by.get("certification", []):
        v = f.value
        m.certifications.append(Entry("certification", f.id, v.get("name") or "",
                                      v.get("issuer") or "", format_date(v.get("date")), "",
                                      url=v.get("url") or ""))
    groups: dict[str, SkillGroup] = {}
    for f in by.get("skill", []):
        v = f.value
        g = groups.setdefault(v.get("category") or "Other", SkillGroup(
            v.get("category") or "Other", [], []))
        if v.get("name") and v["name"].lower() not in (n.lower() for n in g.names):
            g.names.append(v["name"])
            g.fact_ids.append(f.id)
    m.skill_groups = list(groups.values())
    m.fact_ids = {f.id for f in facts}
    return m
