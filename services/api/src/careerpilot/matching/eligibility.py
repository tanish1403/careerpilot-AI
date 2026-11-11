"""Eligibility: per MANDATORY requirement satisfied / not_satisfied / unknown.

Rules: unknown is never treated as satisfied; unconfirmed (proposed) profile facts are not evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.enums import TriState
from ..job_connectors.requirements import degree_level
from .profile import ProfileSnapshot, as_list, ev

_RANK = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}


@dataclass
class Req:
    id: str | None
    text: str
    kind: str
    mandatory: bool
    normalized: str | None


def _res(r: Req, state: TriState, reason: str, evidence: list[dict] | None = None) -> dict:
    return {"requirement": r.text, "requirement_id": r.id, "kind": r.kind, "normalized": r.normalized,
            "mandatory": r.mandatory, "state": state.value, "evidence": evidence or [], "reason": reason}


def evaluate_requirement(r: Req, snap: ProfileSnapshot) -> dict:
    n = r.normalized or ""
    if r.kind == "skill":
        credit, e = snap.skill_evidence(n)
        if e:
            return _res(r, TriState.SATISFIED, f"confirmed evidence of {n}", [e])
        un = snap.unconfirmed_skill_names.get(n)
        if un:
            return _res(r, TriState.UNKNOWN, f"{n} appears in your profile but is not confirmed; "
                        "confirm it to count as evidence", [un.ev()])
        return _res(r, TriState.NOT_SATISFIED, f"no confirmed evidence of {n} in your profile")
    if r.kind == "experience":
        need = int(n.split(":")[1]) if ":" in n else 0
        yrs = snap.experience_years()
        if yrs is None:
            return _res(r, TriState.UNKNOWN, "no confirmed dated experience to compare against")
        evs = [e.ev() for e in snap.experiences if e.confirmed]
        if yrs >= need:
            return _res(r, TriState.SATISFIED, f"{yrs:g} confirmed years >= {need} required", evs)
        return _res(r, TriState.NOT_SATISFIED, f"{yrs:g} confirmed years < {need} required", evs)
    if r.kind == "education":
        need = n.split(":")[1] if ":" in n else "bachelor"
        lvl, item = snap.best_degree()
        flexible = bool(re.search(r"equivalent|or related|or relevant experience", r.text, re.I))
        if lvl is None:
            return _res(r, TriState.UNKNOWN, "no confirmed degree in your profile")
        if _RANK[lvl] >= _RANK.get(need, 2):
            return _res(r, TriState.SATISFIED, f"confirmed {lvl} degree meets {need}", [item.ev()])
        if flexible:
            return _res(r, TriState.UNKNOWN, "below the stated degree but the posting accepts equivalent "
                        "experience", [item.ev()])
        return _res(r, TriState.NOT_SATISFIED, f"highest confirmed degree is {lvl}, {need} required",
                    [item.ev()])
    if r.kind == "authorization":
        wa = snap.preferences.get("work_authorization")
        wa = wa if isinstance(wa, dict) else {}
        if n == "authorization:no_sponsorship":
            ns = wa.get("needs_sponsorship")
            if ns is None:
                return _res(r, TriState.UNKNOWN, "you have not declared whether you need sponsorship")
            return _res(r, TriState.NOT_SATISFIED if ns else TriState.SATISFIED,
                        "based on your declared sponsorship need",
                        [ev("preference", "work_authorization", "declared sponsorship need", True)])
        if n == "authorization:work_authorization":
            regions = [x.lower() for x in as_list(wa.get("authorized_regions"))]
            if regions and any(re.search(rf"\b{re.escape(x)}\b", r.text.lower()) for x in regions):
                return _res(r, TriState.SATISFIED, "matches a region you declared authorization for",
                            [ev("preference", "work_authorization", "declared work authorization", True)])
        return _res(r, TriState.UNKNOWN, "needs your own declaration; CareerPilot never guesses "
                    "authorization, clearance or legal status")
    if r.kind == "location":
        place = n.split(":", 1)[1] if ":" in n else ""
        loc = (snap.location or "").lower()
        locs = [x.lower() for x in as_list(snap.preferences.get("locations"))]
        if not loc and not locs:
            return _res(r, TriState.UNKNOWN, "no location in your profile")
        pool = [loc] + locs
        if place and any(place in p or (p and p in place) for p in pool if p):
            return _res(r, TriState.SATISFIED, f"profile location matches '{place}'",
                        [ev("profile", "location", snap.location or ", ".join(locs), True)])
        if snap.preferences.get("willing_to_relocate") is True:
            return _res(r, TriState.UNKNOWN, "you indicated willingness to relocate; not a confirmed fact")
        if not place:
            return _res(r, TriState.UNKNOWN, "on-site/relocation condition could not be parsed precisely")
        return _res(r, TriState.NOT_SATISFIED, f"profile location differs from '{place}'")
    return _res(r, TriState.UNKNOWN, "cannot be checked automatically")


def evaluate_eligibility(reqs: list[Req], snap: ProfileSnapshot) -> tuple[str, list[dict]]:
    details = [evaluate_requirement(r, snap) for r in reqs if r.mandatory]
    if not details:
        return TriState.UNKNOWN.value, [{
            "requirement": "No mandatory requirements could be detected in the job text", "requirement_id": None,
            "kind": "other", "normalized": None, "mandatory": True, "state": "unknown", "evidence": [],
            "reason": "nothing to check; read the posting yourself"}]
    states = {d["state"] for d in details}
    if TriState.NOT_SATISFIED.value in states:
        return TriState.NOT_SATISFIED.value, details
    if TriState.UNKNOWN.value in states:
        return TriState.UNKNOWN.value, details
    return TriState.SATISFIED.value, details
