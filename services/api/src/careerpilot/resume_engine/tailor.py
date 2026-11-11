"""Deterministic tailoring. Only RE-ORDERS and SELECTS existing confirmed content. Dates,
titles, organisations, degrees and metrics are never touched; no skill is ever added. An
optional LLM reword callable may rephrase bullets, but every rewording must pass
validate_rewording or it is discarded."""
from __future__ import annotations

import copy
import re
from collections.abc import Callable

from ..core.untrusted import injection_flags, wrap_untrusted
from . import keywords as kw
from .model import Bullet, Entry, ResumeModel, SkillGroup

RewordFn = Callable[[str, str], "str | None"]   # (bullet_text, wrapped_job_text) -> new text

_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?[kKmMbB]?")
_NUMWORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
             "hundred", "thousand", "million", "billion", "dozen", "half", "double", "triple",
             "twice"}
_WORD = re.compile(r"[^\W\d_][\w'+#./&-]*", re.U)
_URLISH = re.compile(r"https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+|\bwww\.\S+", re.I)


def _norm_num(s: str) -> str:
    return s.replace(",", "").lower().lstrip("$")


def validate_rewording(new: str, source: str, original: str) -> tuple[bool, str]:
    """Reject any rewording that introduces a number, date, proper noun, technology or URL not
    present in the source evidence, or that changes length wildly."""
    new = (new or "").strip()
    if not new:
        return False, "empty"
    if len(new) > 1.6 * len(original) + 20 or len(new) < 0.4 * len(original):
        return False, "length changed too much"
    src_low = source.lower()
    src_nums = {_norm_num(n) for n in _NUM.findall(source)}
    for n in _NUM.findall(new):
        if _norm_num(n) not in src_nums:
            return False, f"number/date not in evidence: {n}"
    src_words = {w.lower() for w in _WORD.findall(source)}
    for w in re.findall(r"[a-z]+", new.lower()):
        if w in _NUMWORDS and w not in src_words:
            return False, f"quantity word not in evidence: {w}"
    for u in _URLISH.findall(new):
        if u.lower() not in src_low:
            return False, f"link not in evidence: {u}"
    words = _WORD.findall(new)
    for i, w in enumerate(words):
        core = w.strip(".,;:()'\"")
        if not core:
            continue
        proper = (core[0].isupper() and i > 0) or (core.isupper() and len(core) >= 2) or \
            any(c.isupper() for c in core[1:])
        if proper and core.lower() not in src_words and core.lower() not in src_low:
            return False, f"proper noun/acronym not in evidence: {core}"
    for t in kw.TECH_TERMS:
        if len(t) > 1 and kw.phrase_in(new, t) and not kw.phrase_in(source, t):
            return False, f"technology not in evidence: {t}"
    return True, "ok"


def jd_text_from(title: str | None, company: str | None, description: str | None,
                 requirements: list | None = None) -> str:
    parts = [title or "", description or ""]
    parts += [r if isinstance(r, str) else str(r.get("text", "")) if isinstance(r, dict) else ""
              for r in (requirements or [])]
    return "\n".join(p for p in parts if p)


def tailor(model: ResumeModel, jd: str, *, max_bullets: int = 5, max_projects: int = 4,
           reword: RewordFn | None = None) -> tuple[ResumeModel, dict]:
    """Return (tailored copy, report). The input model is never mutated."""
    m = copy.deepcopy(model)
    jd_terms = kw.terms(jd)
    skill_names = [n for g in m.skill_groups for n in g.names]
    haystack = " ".join(
        [e.title + " " + e.org + " " + " ".join(b.text for b in e.bullets) + " "
         + " ".join(e.technologies) for e in m.entries()] + skill_names
        + ([m.summary[0]] if m.summary else []))
    sc = lambda text: kw.score_text(text, jd_terms, skill_names, jd)  # noqa: E731
    omitted = 0
    rewordings: list[dict] = []
    rejected: list[dict] = []
    wrapped = wrap_untrusted(jd[:6000], "job_description") if reword else ""

    def order_bullets(e: Entry, cap: int) -> None:
        nonlocal omitted
        scored = [(sc(b.text), -i, b) for i, b in enumerate(e.bullets)]
        keep = sorted(scored, key=lambda t: (t[0], t[1]), reverse=True)[:cap]
        keep_ids = {id(t[2]) for t in keep}
        omitted += len(e.bullets) - len(keep)
        ranked = sorted((t for t in scored if id(t[2]) in keep_ids),
                        key=lambda t: (t[0], t[1]), reverse=True)
        e.bullets = [t[2] for t in ranked]
        if reword:
            ctx = " ".join([e.title, e.org, e.location, " ".join(e.technologies)])
            for b in e.bullets:
                try:
                    new = reword(b.text, wrapped)
                except Exception:  # noqa: BLE001
                    new = None
                if not new or new.strip() == b.text:
                    continue
                ok, why = validate_rewording(new, b.source_text + " " + ctx, b.source_text)
                if ok:
                    rewordings.append({"fact_id": e.fact_id, "original": b.text,
                                       "new": new.strip()})
                    b.text, b.reworded = new.strip(), True
                else:
                    rejected.append({"fact_id": e.fact_id, "original": b.text,
                                     "proposed": new.strip()[:300], "reason": why})

    for e in m.experiences:                 # all roles kept, dates/titles untouched
        order_bullets(e, max_bullets)
    scored_projects = sorted(m.projects, key=lambda e: sc(e.title + " " + e.org + " "
                                                          + " ".join(b.text for b in e.bullets)),
                             reverse=True)
    dropped_projects = max(0, len(scored_projects) - max_projects)
    m.projects = scored_projects[:max_projects]
    for e in m.projects:
        order_bullets(e, 3)
    for g in m.skill_groups:                # re-order only; nothing added
        g.names, g.fact_ids = _reorder(g, jd)
    m.skill_groups.sort(key=lambda g: -sum(1 for n in g.names if kw.phrase_in(jd, n)))
    matched = sorted({n for n in skill_names if kw.phrase_in(jd, n)}
                     | {t for t in kw.jd_tech(jd) if kw.phrase_in(haystack, t)})
    missing = [t for t in kw.jd_tech(jd) if not kw.phrase_in(haystack, t)]
    report = {"matched_keywords": matched[:40], "missing_keywords": missing[:40],
              "missing_note": "JD keywords with no support in your confirmed facts; NOT added.",
              "omitted_bullets": omitted, "omitted_projects": dropped_projects,
              "rewordings": rewordings, "rejected_rewordings": rejected,
              "injection_flags": injection_flags(jd)}
    return m, report


def _reorder(g: SkillGroup, jd: str) -> tuple[list[str], list[str]]:
    idx = sorted(range(len(g.names)), key=lambda i: (not kw.phrase_in(jd, g.names[i]), i))
    return [g.names[i] for i in idx], [g.fact_ids[i] for i in idx]


def check_integrity(master: ResumeModel, tailored: ResumeModel) -> list[str]:
    """Return a list of violations (empty = tailoring only selected/re-ordered/validated)."""
    problems: list[str] = []
    mem = {e.fact_id: e for e in master.entries()}
    for e in tailored.entries():
        src = mem.get(e.fact_id)
        if src is None:
            problems.append(f"entry {e.fact_id} is not a confirmed fact")
            continue
        for f in ("kind", "title", "org", "dates", "location", "url"):
            if getattr(e, f) != getattr(src, f):
                problems.append(f"{e.kind} {e.fact_id}: {f} changed")
        originals = {b.text for b in src.bullets}
        for b in e.bullets:
            if b.text in originals:
                continue
            if not b.reworded:
                problems.append(f"{e.kind} {e.fact_id}: bullet not from confirmed facts")
                continue
            ok, why = validate_rewording(b.text, b.source_text + " " + src.title + " " + src.org,
                                         b.source_text)
            if not ok:
                problems.append(f"{e.kind} {e.fact_id}: invalid rewording ({why})")
    allowed_skills = {n.lower() for g in master.skill_groups for n in g.names}
    for g in tailored.skill_groups:
        for n in g.names:
            if n.lower() not in allowed_skills:
                problems.append(f"skill '{n}' is not a confirmed skill")
    if tailored.summary != master.summary:
        problems.append("summary changed")
    if tailored.name != master.name:
        problems.append("name changed")
    return problems


_ = Bullet
