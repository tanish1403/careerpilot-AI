"""Cover-letter draft generator. Same evidence rules as resumes: every statement about the
candidate comes from a confirmed fact (with evidence ids) or is flagged for confirmation."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..core.untrusted import wrap_untrusted
from ..db.base import new_id
from ..db.models import CandidateProfile, Job, ResumeVersion
from . import keywords as kw
from .model import Entry, build_model
from .tailor import RewordFn, jd_text_from, validate_rewording
from .versions import claims_of

_PAST = {"led", "built", "ran", "wrote", "drove", "won", "made", "managed", "grew", "cut",
         "began", "taught", "developed", "created", "designed"}


def _sentence(entry: Entry, bullet: str) -> str:
    first, _, rest = bullet.partition(" ")
    f_low = first.lower()
    verb = first[:1].isupper() and first[1:].islower() and (f_low.endswith("ed")
                                                            or f_low in _PAST)
    who = f"At {entry.org}" if entry.org else "In a previous role"
    role = f" as {entry.title}" if entry.title and entry.kind == "experience" else ""
    if entry.kind == "project":
        who, role = f"In my project {entry.title}", ""
    body = f"I {f_low} {rest}".strip() if verb else f"my work included: {bullet}"
    s = f"{who}{role}, {body}"
    return s if s.endswith((".", "!", "?")) else s + "."


def generate_cover_letter(db: Session, profile: CandidateProfile, job: Job, *,
                          resume: ResumeVersion | None = None,
                          rewrite: RewordFn | None = None, max_points: int = 3) -> dict:
    model = build_model(db, profile)
    jd = jd_text_from(job.title, job.company_name, job.description, job.requirements)
    jd_terms = kw.terms(jd)
    skill_names = [n for g in model.skill_groups for n in g.names]
    allowed: set[str] | None = None
    if resume is not None:
        allowed = {c.text for c in claims_of(db, resume) if not c.needs_confirmation}
    cands: list[tuple[float, int, Entry, str]] = []
    for ei, e in enumerate(model.experiences + model.projects):
        for b in e.bullets:
            if allowed is not None and b.text not in allowed:
                continue
            cands.append((kw.score_text(b.text, jd_terms, skill_names, jd), -ei, e, b.text))
    cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
    picked = [c for c in cands if c[0] > 0][:max_points] or cands[:min(2, max_points)]

    claims: list[dict] = []
    paras: list[str] = []
    wrapped = wrap_untrusted(jd[:6000], "job_description") if rewrite else ""
    greeting = "Dear Hiring Manager,"
    paras.append(f"I am writing to apply for the {job.title} position at {job.company_name}.")

    def add(text: str, evidence: list[str], source: str) -> None:
        needs = not evidence
        if rewrite:
            try:
                new = rewrite(text, wrapped)
            except Exception:  # noqa: BLE001
                new = None
            if new and new.strip() != text:
                ok, _ = validate_rewording(new, source, text)
                if ok:
                    text, needs = new.strip(), True
        paras.append(text)
        claims.append({"id": new_id(), "text": text, "evidence_ids": evidence,
                       "needs_confirmation": needs})

    for _s, _o, e, bullet in picked:
        add(_sentence(e, bullet), [e.fact_id], f"{bullet} {e.title} {e.org}")
    rel = [n for n in skill_names if kw.phrase_in(jd, n)]
    if rel:
        ids = [fid for g in model.skill_groups for n, fid in zip(g.names, g.fact_ids)
               if n in rel]
        add("My confirmed skills relevant to this role include " + _join(rel[:8]) + ".", ids,
            ", ".join(rel))
    if model.education:
        ed = model.education[0]
        if ed.title and ed.org:
            add(f"I hold {ed.title} from {ed.org}.", [ed.fact_id], f"{ed.title} {ed.org}")
    paras.append("Thank you for considering my application. I would welcome the chance to "
                 "discuss how I can contribute to your team.")
    body = "\n\n".join(paras)
    name = model.name or ""
    text = f"{greeting}\n\n{body}\n\nSincerely,\n{name}".rstrip()
    return {"text": text, "claims": claims,
            "needs_confirmation": [c["text"] for c in claims if c["needs_confirmation"]],
            "evidence_note": "Every statement about you maps to confirmed facts via evidence_ids."}


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


_ = re
