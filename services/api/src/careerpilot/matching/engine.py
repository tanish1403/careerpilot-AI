"""Deterministic fit + priority scoring. Pure functions of (profile snapshot, job context, config, as_of)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..job_connectors.normalize import parse_salary_range
from .config import DISCLAIMER, MatchConfig
from .eligibility import Req, evaluate_eligibility
from .profile import ProfileSnapshot, as_list, ev
from .taxonomy import find_domains, find_skills, role_families

SENIORITY_LEVEL = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "staff": 4, "manager": 4,
                   "principal": 5, "director": 6}
EFFORT_BY_SOURCE = {"greenhouse": 1.0, "ashby": 1.0, "lever": 1.0, "career_page": 0.7, "url": 0.5,
                    "jobspy": 0.5, "manual": 0.4}


@dataclass
class JobCtx:
    id: str
    title: str
    company: str
    location: str | None
    work_mode: str
    description: str
    seniority: str | None
    salary_text: str | None
    posted_at: datetime | None
    first_seen_at: datetime
    status: str
    version: int
    requirements: list[Req] = field(default_factory=list)
    source_kinds: list[str] = field(default_factory=list)
    valid_through: datetime | None = None


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n)


def _factor(weight: float, score: float, evidence: list[dict], note: str = "", insufficient: bool = False) -> dict:
    score = max(0.0, min(1.0, score))
    return {"weight": _r(weight, 4), "score": _r(score), "contribution": _r(weight * score * 100, 2),
            "evidence": evidence, "note": note, "insufficient_data": insufficient}


def level_from_years(y: float) -> int:
    return 0 if y < 1 else 1 if y < 2 else 2 if y < 5 else 3 if y < 8 else 4 if y < 12 else 5


def _job_text(job: JobCtx) -> str:
    return f"{job.title}\n{job.description[:8000]}"


def _skills_factor(job: JobCtx, snap: ProfileSnapshot, missing: list[dict]) -> tuple[float, list[dict], str, bool]:
    weights: dict[str, float] = {}
    mand: dict[str, bool] = {}
    for r in job.requirements:
        if r.kind == "skill" and r.normalized:
            weights[r.normalized] = max(weights.get(r.normalized, 0), 1.0 if r.mandatory else 0.5)
            mand[r.normalized] = mand.get(r.normalized, False) or r.mandatory
    basis = "requirements"
    if not weights:
        basis = "mentioned in description"
        for s in find_skills(_job_text(job))[:12]:
            weights[s] = 0.5
    if not weights:
        return 0.5, [], "no technical skills detected in the job text", True
    got, tot, evid = 0.0, 0.0, []
    for s, w in weights.items():
        credit, e = snap.skill_evidence(s)
        got += w * credit
        tot += w
        if e:
            evid.append({**e, "skill": s, "credit": credit})
        else:
            un = snap.unconfirmed_skill_names.get(s)
            missing.append({"requirement": s, "kind": "skill", "mandatory": mand.get(s, False),
                            "reason": "listed in profile but unconfirmed" if un else "no confirmed evidence"})
    return got / tot, evid, f"{len(evid)}/{len(weights)} skills evidenced ({basis})", False


def _experience_factor(job: JobCtx, snap: ProfileSnapshot, missing: list[dict]) -> tuple[float, list[dict], str, bool]:
    yrs = snap.experience_years()
    need = [int(r.normalized.split(":")[1]) for r in job.requirements
            if r.kind == "experience" and r.normalized and r.mandatory]
    evid = [e.ev() for e in snap.experiences if e.confirmed]
    if yrs is None:
        if need or job.seniority:
            missing.append({"requirement": f"{max(need)}+ years" if need else f"{job.seniority} level",
                            "kind": "experience", "mandatory": bool(need),
                            "reason": "no confirmed dated experience"})
        return 0.0, [], "no confirmed dated experience in profile", False
    if need:
        n = max(need)
        if yrs < n:
            missing.append({"requirement": f"{n}+ years experience", "kind": "experience", "mandatory": True,
                            "reason": f"{yrs:g} confirmed years"})
        return min(1.0, yrs / n), evid, f"{yrs:g} confirmed years vs {n} required", False
    if job.seniority in SENIORITY_LEVEL:
        diff = abs(level_from_years(yrs) - SENIORITY_LEVEL[job.seniority])
        return max(0.0, 1 - 0.35 * diff), evid, f"{yrs:g} years vs {job.seniority} level", False
    return 0.5, evid, "job states no experience level", True


def _projects_factor(job: JobCtx, snap: ProfileSnapshot) -> tuple[float, list[dict], str, bool]:
    projs = snap.confirmed(snap.projects)
    skills = [r.normalized for r in job.requirements if r.kind == "skill" and r.normalized] or \
        find_skills(_job_text(job))[:12]
    skills = list(dict.fromkeys(skills))
    if not skills:
        return 0.5, [], "no skills to compare against projects", True
    if not projs:
        return 0.0, [], "no confirmed projects in profile", False
    evid, hit = [], 0
    from .taxonomy import find_skills as fs
    for s in skills:
        for p in projs:
            if s in fs(p.text + " " + " ".join(p.extra.get("tech", []))):
                hit += 1
                evid.append({**p.ev(), "skill": s})
                break
    return hit / len(skills), evid, f"{hit}/{len(skills)} job skills shown in confirmed projects", False


def _education_factor(job: JobCtx, snap: ProfileSnapshot) -> tuple[float, list[dict], str, bool]:
    reqs = [r for r in job.requirements if r.kind == "education"]
    if not reqs:
        return 0.5, [], "job states no degree requirement", True
    from .eligibility import evaluate_requirement
    states = [evaluate_requirement(r, snap) for r in reqs]
    evid = [e for s in states for e in s["evidence"]]
    if any(s["state"] == "not_satisfied" for s in states):
        return 0.1, evid, "degree requirement not met by confirmed education", False
    if any(s["state"] == "unknown" for s in states):
        return 0.3, evid, "degree requirement cannot be confirmed", False
    return 1.0, evid, "degree requirement met", False


def _domain_factor(job: JobCtx, snap: ProfileSnapshot) -> tuple[float, list[dict], str, bool]:
    jd = find_domains(_job_text(job))
    if not jd:
        return 0.5, [], "no specific domain detected in the job text", True
    pd = snap.text_domains()
    for t in (snap.headline, snap.summary):
        pass            # headline/summary are self-description, not confirmed evidence
    hit = [d for d in jd if d in pd]
    evid = [{**pd[d][0].ev(), "domain": d} for d in hit]
    return len(hit) / len(jd), evid, f"{len(hit)}/{len(jd)} job domains in confirmed experience/projects", False


def _role_factor(job: JobCtx, snap: ProfileSnapshot) -> tuple[float, list[dict], str, bool]:
    jf = set(role_families(job.title)) - {"software"} or set(role_families(job.title))
    prefs = as_list(snap.preferences.get("roles"))
    pf = {f for p in prefs for f in role_families(p)} | set(prefs and [p.lower() for p in prefs])
    ef: set[str] = set()
    ev_items = []
    for e in snap.experiences:
        if e.confirmed:
            fam = set(role_families(e.extra.get("title") or ""))
            if fam & jf:
                ev_items.append(e.ev())
            ef |= fam
    if not prefs and not ef:
        return 0.0, [], "no role preferences or confirmed job titles in profile", False
    best = 0.0
    note = "no overlap with preferred roles or past titles"
    jt = job.title.lower()
    if jf and jf & {f for p in prefs for f in role_families(p)}:
        best, note = 1.0, "job role family matches your preferred roles"
        ev_items.append(ev("preference", "roles", ", ".join(prefs), True))
    elif any(p.lower() in jt for p in prefs):
        best, note = 1.0, "job title contains a preferred role"
        ev_items.append(ev("preference", "roles", ", ".join(prefs), True))
    elif jf & ef:
        best, note = 0.7, "job role family matches a confirmed past title"
    elif "software" in role_families(job.title) and (ef or prefs):
        best, note = 0.4, "generic software role"
    return best, ev_items, note, False


def _location_factor(job: JobCtx, snap: ProfileSnapshot) -> tuple[float, list[dict], str, bool]:
    prefs = snap.preferences
    modes = [m.lower() for m in as_list(prefs.get("work_modes") or prefs.get("work_mode"))]
    locs = [x.lower() for x in as_list(prefs.get("locations"))]
    if snap.location:
        locs.append(snap.location.lower())
    if not modes and not locs:
        return 0.5, [], "no location/work-mode preferences set", True
    pe = ev("preference", "location", ", ".join(modes + locs), True)
    jl = (job.location or "").lower()
    loc_hit = bool(jl) and any(x and (x.split(",")[0].strip() in jl or jl.split(",")[0].strip() in x) for x in locs)
    if job.work_mode == "remote":
        if not modes or "remote" in modes or prefs.get("remote_ok") is True:
            return 1.0, [pe], "remote role and you accept remote", False
        return (0.8 if loc_hit else 0.3), [pe], "remote role but remote not in your preferences", False
    if job.work_mode == "unknown" and not jl:
        return 0.5, [pe], "job location/work mode not stated", True
    mode_ok = not modes or job.work_mode in modes or job.work_mode == "unknown"
    if loc_hit and mode_ok:
        return 1.0, [pe], "location and work mode match", False
    if loc_hit:
        return 0.6, [pe], "location matches but work mode differs", False
    if prefs.get("willing_to_relocate") is True:
        return 0.4, [pe], "different location; you are open to relocating", False
    return 0.0, [pe], "location does not match your preferences", False


def freshness_score(job: JobCtx, as_of: datetime) -> tuple[float, int]:
    ref = _aware(job.posted_at) or _aware(job.first_seen_at)
    age = max(0, (as_of - ref).days)
    if job.status == "closed":
        return 0.0, age
    return (1.0 if age <= 3 else max(0.0, 1 - (age - 3) / 42)), age


def _fresh_factor(job: JobCtx, as_of: datetime) -> tuple[float, list[dict], str, bool]:
    s, age = freshness_score(job, as_of)
    src = "posted" if job.posted_at else "first seen"
    return s, [], f"{src} {age} day(s) ago" + (" (job is closed)" if job.status == "closed" else ""), False


def compute_fit(job: JobCtx, snap: ProfileSnapshot, cfg: MatchConfig, as_of: datetime) -> tuple[float, dict, list[dict]]:
    missing: list[dict] = []
    parts = {
        "technical_skills": _skills_factor(job, snap, missing),
        "experience": _experience_factor(job, snap, missing),
        "projects": _projects_factor(job, snap),
        "education": _education_factor(job, snap),
        "domain": _domain_factor(job, snap),
        "role_alignment": _role_factor(job, snap),
        "location": _location_factor(job, snap),
        "freshness": _fresh_factor(job, as_of),
    }
    factors = {k: _factor(cfg.weights[k], s, e, note, insuff) for k, (s, e, note, insuff) in parts.items()}
    fit = sum(f["contribution"] for f in factors.values())
    return _r(fit, 1), factors, missing


def compute_priority(job: JobCtx, snap: ProfileSnapshot, cfg: MatchConfig, fit: float, factors: dict,
                     eligibility: str, as_of: datetime) -> tuple[float, dict]:
    prefs = snap.preferences
    # urgency
    vt = _aware(job.valid_through)
    if vt is not None and vt >= as_of:
        days = (vt - as_of).days
        urgency, un = (1.0, f"closes in {days} day(s)") if days <= 14 else (0.5, f"closes in {days} day(s)")
    else:
        _, age = freshness_score(job, as_of)
        urgency, un = (0.7, "recently posted; early applicants are seen first") if age <= 7 else (0.3, "no deadline known")
    # preference alignment
    align: list[float] = []
    notes: list[str] = []
    modes = [m.lower() for m in as_list(prefs.get("work_modes") or prefs.get("work_mode"))]
    if modes and job.work_mode != "unknown":
        align.append(1.0 if job.work_mode in modes else 0.0)
        notes.append("work mode " + ("matches" if align[-1] else "differs"))
    sen = [s.lower() for s in as_list(prefs.get("seniority"))]
    if sen and job.seniority:
        align.append(1.0 if job.seniority in sen else 0.0)
        notes.append("seniority " + ("matches" if align[-1] else "differs"))
    smin = prefs.get("salary_min") or prefs.get("min_salary")
    rng = parse_salary_range(job.salary_text)
    if isinstance(smin, (int, float)) and rng:
        align.append(1.0 if rng[1] >= smin else 0.0)
        notes.append("salary " + ("meets minimum" if align[-1] else "below minimum"))
    if factors["location"]["insufficient_data"] is False:
        align.append(factors["location"]["score"])
    pref_score = sum(align) / len(align) if align else 0.5
    # effort
    effort = max([EFFORT_BY_SOURCE.get(k, 0.5) for k in job.source_kinds] or [0.5])
    # goals
    goals = [g.lower() for g in as_list(prefs.get("goals"))]
    text = _job_text(job).lower()
    goal_hits = [g for g in goals if g in text]
    goal_score = len(goal_hits) / len(goals) if goals else 0.5
    comps = {"fit": (fit / 100, f"fit score {fit}"), "freshness": (factors["freshness"]["score"], factors["freshness"]["note"]),
             "urgency": (urgency, un), "preference_alignment": (pref_score, "; ".join(notes) or "no preference signals"),
             "effort": (effort, f"sources: {', '.join(job.source_kinds) or 'unknown'}"),
             "goals": (goal_score, f"matched goals: {', '.join(goal_hits)}" if goals else "no goals set")}
    breakdown = {k: {"weight": _r(cfg.priority_weights[k], 4), "score": _r(s), "note": n,
                     "contribution": _r(cfg.priority_weights[k] * s * 100, 2)} for k, (s, n) in comps.items()}
    base = sum(b["contribution"] for b in breakdown.values())
    mult = 1.0
    reasons = []
    if eligibility == "not_satisfied":
        mult *= 0.5
        reasons.append("eligibility not satisfied (x0.5)")
    elif eligibility == "unknown":
        mult *= 0.9
        reasons.append("eligibility unknown (x0.9)")
    if job.status == "closed":
        mult *= 0.1
        reasons.append("job closed (x0.1)")
    return _r(base * mult, 1), {"components": breakdown, "base": _r(base, 2), "multiplier": mult,
                                "adjustments": reasons}


def score(job: JobCtx, snap: ProfileSnapshot, cfg: MatchConfig, as_of: datetime) -> dict:
    elig, details = evaluate_eligibility(job.requirements, snap)
    fit, factors, missing = compute_fit(job, snap, cfg, as_of)
    for d in details:
        if d["state"] != "satisfied" and d["requirement_id"] is not None and not any(
                m["requirement"] == (d["normalized"] or d["requirement"]) for m in missing):
            missing.append({"requirement": d["normalized"] or d["requirement"], "kind": d["kind"], "mandatory": True,
                            "reason": d["reason"], "state": d["state"]})
    prio, pb = compute_priority(job, snap, cfg, fit, factors, elig, as_of)
    return {"eligibility": elig, "eligibility_details": details, "fit_score": fit, "priority_score": prio,
            "factors": factors, "missing": missing,
            "evidence": {"priority": pb, "disclaimer": DISCLAIMER,
                         "meta": {"as_of": as_of.isoformat(), "algo": "1"}}}
