"""Profile, fact and typed-item logic (Lane B). Facts are the evidence record; typed rows are
materialised from facts. The profile `version` is bumped on ANY change of confirmed data."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..core.audit import audit
from ..db.base import utcnow
from ..db.models import (CandidateProfile, Certification, Education, Experience, ProfileFact,
                         Project, Publication, Skill)
from .dates import month_index, parse_ym
from .factschema import (ITEM_CATEGORIES, fact_key, fact_text, missing_required, normalize_value)

WS = "default"
ROW_MODELS: dict[str, tuple[type, tuple[str, ...]]] = {
    "experience": (Experience, ("company", "title", "location", "start_date", "end_date",
                                "bullets")),
    "education": (Education, ("institution", "degree", "field", "start_date", "end_date",
                              "grade")),
    "skill": (Skill, ("name", "category", "level", "years")),
    "project": (Project, ("name", "description", "url", "technologies", "bullets")),
    "publication": (Publication, ("title", "venue", "year", "url")),
    "certification": (Certification, ("name", "issuer", "date", "url")),
}
LIST_FIELDS = {"bullets", "technologies"}
ROUTE_CATEGORY = {"experiences": "experience", "education": "education", "skills": "skill",
                  "projects": "project", "publications": "publication",
                  "certifications": "certification"}


class ProfileError(Exception):
    def __init__(self, status: int, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


# ------------------------------------------------------------------ profile
def get_profile(db: Session) -> CandidateProfile:
    p = db.query(CandidateProfile).filter_by(workspace_id=WS).filter(
        CandidateProfile.deleted_at.is_(None)).order_by(CandidateProfile.created_at).first()
    if p is None:
        p = CandidateProfile(workspace_id=WS, links={}, preferences={}, version=1)
        db.add(p)
        db.flush()
    return p


def bump_version(db: Session, profile: CandidateProfile) -> None:
    profile.version = (profile.version or 1) + 1
    profile.updated_at = utcnow()
    db.flush()


def _fact_query(db: Session, profile: CandidateProfile):
    return db.query(ProfileFact).filter(ProfileFact.profile_id == profile.id,
                                        ProfileFact.deleted_at.is_(None))


def confirmed_facts(db: Session, profile: CandidateProfile, category: str | None = None
                    ) -> list[ProfileFact]:
    q = _fact_query(db, profile).filter(ProfileFact.status == "confirmed")
    if category:
        q = q.filter(ProfileFact.category == category)
    return q.order_by(ProfileFact.created_at, ProfileFact.id).all()


def profile_dict(db: Session, p: CandidateProfile, *, full: bool = True) -> dict:
    d = {"id": p.id, "full_name": p.full_name, "headline": p.headline, "email": p.email,
         "phone": p.phone, "location": p.location, "links": p.links or {},
         "summary": p.summary, "preferences": p.preferences or {}, "version": p.version,
         "created_at": p.created_at, "updated_at": p.updated_at}
    if full:
        d["completeness"] = completeness(db, p)
        d["contradictions"] = contradictions(db, p)
    return d


_PROFILE_FIELDS = ("full_name", "headline", "email", "phone", "location", "summary")


def update_profile(db: Session, p: CandidateProfile, data: dict[str, Any]) -> CandidateProfile:
    changed = False
    for k in _PROFILE_FIELDS:
        if k in data:
            v = (str(data[k]).strip() if data[k] is not None else None) or None
            if v != getattr(p, k):
                setattr(p, k, v)
                changed = True
                if k == "summary":
                    _sync_summary_fact(db, p, v)
    for k in ("links", "preferences"):
        if k in data and data[k] is not None:
            if not isinstance(data[k], dict):
                raise ProfileError(422, f"{k} must be an object")
            if data[k] != (getattr(p, k) or {}):
                setattr(p, k, data[k])
                changed = changed or k == "links"
    if changed:
        bump_version(db, p)
        audit(db, "profile.update", subject_type="profile", subject_id=p.id,
              detail={"fields": [k for k in data if k in (*_PROFILE_FIELDS, "links")]})
    db.flush()
    return p


def _sync_summary_fact(db: Session, p: CandidateProfile, text: str | None) -> None:
    """A summary the user typed is user-attested evidence: keep a confirmed summary fact."""
    for f in confirmed_facts(db, p, "summary"):
        if f.source_document_id is None:
            f.deleted_at = utcnow()
    if text:
        db.add(ProfileFact(profile_id=p.id, workspace_id=WS, category="summary", key="summary",
                           value={"text": text}, status="confirmed", confidence=1.0,
                           source_location="user entry"))
    db.flush()


# ------------------------------------------------------------------ facts
def fact_dict(f: ProfileFact) -> dict:
    return {"id": f.id, "profile_id": f.profile_id, "category": f.category, "key": f.key,
            "value": f.value, "status": f.status, "confidence": f.confidence,
            "source_document_id": f.source_document_id, "source_location": f.source_location,
            "parse_run_id": f.parse_run_id, "created_at": f.created_at, "updated_at": f.updated_at}


def get_fact(db: Session, fact_id: str) -> ProfileFact:
    f = db.get(ProfileFact, fact_id)
    if not f or f.deleted_at is not None:
        raise ProfileError(404, "Fact not found")
    return f


def list_facts(db: Session, p: CandidateProfile, *, status: str | None = None,
               category: str | None = None, document_id: str | None = None,
               limit: int = 50, offset: int = 0) -> tuple[list[ProfileFact], int]:
    q = _fact_query(db, p)
    if status:
        q = q.filter(ProfileFact.status == status)
    if category:
        q = q.filter(ProfileFact.category == category)
    if document_id:
        q = q.filter(ProfileFact.source_document_id == document_id)
    total = q.count()
    rows = q.order_by(ProfileFact.created_at, ProfileFact.id).offset(offset).limit(limit).all()
    return rows, total


def create_fact(db: Session, p: CandidateProfile, category: str, value: dict, *,
                status: str = "proposed", confidence: float | None = None,
                source_document_id: str | None = None, source_location: str | None = None,
                parse_run_id: str | None = None) -> ProfileFact:
    try:
        v = normalize_value(category, value)
    except ValueError as e:
        raise ProfileError(422, str(e)) from e
    f = ProfileFact(profile_id=p.id, workspace_id=WS, category=category,
                    key=fact_key(category, v), value=v, status=status, confidence=confidence,
                    source_document_id=source_document_id, source_location=source_location,
                    parse_run_id=parse_run_id)
    db.add(f)
    db.flush()
    return f


def _row_for(db: Session, f: ProfileFact):
    model = ROW_MODELS.get(f.category, (None,))[0]
    if model is None:
        return None
    return db.query(model).filter(model.fact_id == f.id).first()


def materialize(db: Session, p: CandidateProfile, f: ProfileFact, *, create: bool) -> Any:
    """Write the fact's value into its typed row (creating it when `create`)."""
    if f.category in ROW_MODELS:
        model, cols = ROW_MODELS[f.category]
        row = _row_for(db, f)
        if row is None:
            if not create:
                return None
            row = model(profile_id=p.id, workspace_id=WS, fact_id=f.id)
            db.add(row)
        row.deleted_at = None
        row.status = f.status
        for c in cols:
            val = f.value.get(c)
            if c in LIST_FIELDS:
                val = list(val or [])
            setattr(row, c, val)
        if f.category == "experience":
            row.company, row.title = row.company or "", row.title or ""
        db.flush()
        return row
    if f.status == "confirmed":
        v = f.value
        if f.category == "contact":
            for k in ("full_name", "headline", "email", "phone", "location"):
                if v.get(k):
                    setattr(p, k, v[k])
            if v.get("links"):
                p.links = {**(p.links or {}), **v["links"]}
        elif f.category == "summary" and v.get("text"):
            p.summary = v["text"]
        db.flush()
    return None


def confirm_fact(db: Session, p: CandidateProfile, f: ProfileFact, actor: str | None = None
                 ) -> ProfileFact:
    miss = missing_required(f.category, f.value)
    if miss:
        raise ProfileError(422, "Cannot confirm: missing required field(s): " + ", ".join(miss),
                           "missing_fields")
    if f.status == "confirmed":
        return f
    f.status = "confirmed"
    materialize(db, p, f, create=True)
    bump_version(db, p)
    audit(db, "fact.confirm", actor=actor, subject_type="fact", subject_id=f.id,
          detail={"category": f.category})
    return f


def reject_fact(db: Session, p: CandidateProfile, f: ProfileFact, actor: str | None = None
                ) -> ProfileFact:
    was = f.status == "confirmed"
    if f.status == "rejected":
        return f
    f.status = "rejected"
    row = _row_for(db, f)
    if row is not None:
        row.status = "rejected"
    if was:
        if f.category == "summary" and p.summary == f.value.get("text"):
            p.summary = None
        bump_version(db, p)
    audit(db, "fact.reject", actor=actor, subject_type="fact", subject_id=f.id,
          detail={"category": f.category, "was_confirmed": was})
    db.flush()
    return f


def edit_fact(db: Session, p: CandidateProfile, f: ProfileFact, patch: dict, *,
              confirm: bool = False, actor: str | None = None) -> ProfileFact:
    """Edit a fact value. The edit never confirms by itself: an edited confirmed fact drops
    back to 'proposed' unless confirm=True is passed explicitly."""
    try:
        merged = normalize_value(f.category, {**f.value, **patch})
    except ValueError as e:
        raise ProfileError(422, str(e)) from e
    was = f.status == "confirmed"
    f.value = merged
    f.key = fact_key(f.category, merged)
    if confirm:
        miss = missing_required(f.category, merged)
        if miss:
            raise ProfileError(422, "Cannot confirm: missing required field(s): "
                               + ", ".join(miss), "missing_fields")
        f.status = "confirmed"
    elif was:
        f.status = "proposed"
    elif f.status == "rejected":
        f.status = "proposed"
    row = _row_for(db, f)
    if row is not None or f.status == "confirmed":
        materialize(db, p, f, create=f.status == "confirmed")
    if was or f.status == "confirmed":
        bump_version(db, p)
    audit(db, "fact.edit", actor=actor, subject_type="fact", subject_id=f.id,
          detail={"category": f.category, "confirm": confirm})
    db.flush()
    return f


# ------------------------------------------------------------------ typed items
def item_dict(row: Any, category: str) -> dict:
    _, cols = ROW_MODELS[category]
    d = {"id": row.id, "fact_id": row.fact_id, "status": row.status, "profile_id": row.profile_id,
         "created_at": row.created_at, "updated_at": row.updated_at}
    for c in cols:
        d[c] = getattr(row, c)
    return d


def list_items(db: Session, p: CandidateProfile, category: str, *, status: str | None,
               limit: int, offset: int) -> tuple[list[Any], int]:
    model = ROW_MODELS[category][0]
    q = db.query(model).filter(model.profile_id == p.id, model.deleted_at.is_(None))
    if status:
        q = q.filter(model.status == status)
    total = q.count()
    return q.order_by(model.created_at, model.id).offset(offset).limit(limit).all(), total


def get_item(db: Session, category: str, item_id: str) -> Any:
    model = ROW_MODELS[category][0]
    row = db.get(model, item_id)
    if not row or row.deleted_at is not None:
        raise ProfileError(404, "Item not found")
    return row


def create_item(db: Session, p: CandidateProfile, category: str, data: dict,
                actor: str | None = None) -> Any:
    """User-entered item. Typed directly by the user, so it defaults to confirmed."""
    data = dict(data)
    status = data.pop("status", "confirmed")
    if status not in ("proposed", "confirmed"):
        raise ProfileError(422, "status must be 'proposed' or 'confirmed'")
    f = create_fact(db, p, category, data, status=status, confidence=1.0,
                    source_location="user entry")
    miss = missing_required(category, f.value)
    if miss:
        raise ProfileError(422, "Missing required field(s): " + ", ".join(miss))
    row = materialize(db, p, f, create=True)
    if status == "confirmed":
        bump_version(db, p)
    audit(db, "item.create", actor=actor, subject_type=category, subject_id=row.id,
          detail={"status": status})
    return row


def update_item(db: Session, p: CandidateProfile, category: str, item_id: str, data: dict,
                actor: str | None = None) -> Any:
    row = get_item(db, category, item_id)
    f = get_fact(db, row.fact_id) if row.fact_id else None
    if f is None:
        raise ProfileError(409, "Item has no backing fact")
    data = dict(data)
    status = data.pop("status", None)
    if status not in (None, "proposed", "confirmed", "rejected"):
        raise ProfileError(422, "invalid status")
    was = f.status == "confirmed"
    try:
        f.value = normalize_value(category, {**f.value, **data})
    except ValueError as e:
        raise ProfileError(422, str(e)) from e
    f.key = fact_key(category, f.value)
    if status:
        f.status = status
    miss = missing_required(category, f.value)
    if miss and f.status == "confirmed":
        raise ProfileError(422, "Missing required field(s): " + ", ".join(miss))
    materialize(db, p, f, create=True)
    if was or f.status == "confirmed":
        bump_version(db, p)
    audit(db, "item.update", actor=actor, subject_type=category, subject_id=row.id,
          detail={"status": f.status})
    return row


def delete_item(db: Session, p: CandidateProfile, category: str, item_id: str,
                actor: str | None = None) -> None:
    row = get_item(db, category, item_id)
    was = row.status == "confirmed"
    row.deleted_at = utcnow()
    if row.fact_id:
        f = db.get(ProfileFact, row.fact_id)
        if f:
            f.deleted_at = utcnow()
    if was:
        bump_version(db, p)
    audit(db, "item.delete", actor=actor, subject_type=category, subject_id=item_id)
    db.flush()


# ------------------------------------------------------------------ completeness
def completeness(db: Session, p: CandidateProfile) -> dict:
    conf = confirmed_facts(db, p)
    by = {c: [f for f in conf if f.category == c] for c in ITEM_CATEGORIES}
    checks = [
        (15, bool(p.full_name), "full name"),
        (10, bool(p.email), "email"),
        (5, bool(p.phone), "phone"),
        (5, bool(p.location), "location"),
        (5, bool(p.headline), "headline"),
        (10, bool(p.summary), "summary"),
        (20, bool(by["experience"]), "at least one confirmed work experience"),
        (10, bool(by["education"]), "at least one confirmed education entry"),
        (10, len(by["skill"]) >= 5, "at least 5 confirmed skills"),
        (5, bool(p.links), "profile links (LinkedIn, GitHub, portfolio)"),
        (5, bool(p.preferences), "job preferences (roles, locations, work mode)"),
    ]
    score = sum(w for w, ok, _ in checks if ok)
    missing = [m for _, ok, m in checks if not ok]
    pending = _fact_query(db, p).filter(ProfileFact.status == "proposed").count()
    if pending:
        missing.append(f"{pending} extracted fact(s) awaiting your review")
    return {"score": score, "missing": missing}


# ------------------------------------------------------------------ contradictions
def _range(v: dict) -> tuple[int, int] | None:
    s = parse_ym(v.get("start_date"), end=False)
    e = parse_ym(v.get("end_date"), end=True) if v.get("end_date") else None
    if s is None:
        return None
    if e is None:
        e = parse_ym("Present")
    return month_index(s), month_index(e)  # type: ignore[arg-type]


def contradictions(db: Session, p: CandidateProfile) -> list[dict]:
    facts = [f for f in _fact_query(db, p).filter(ProfileFact.status != "rejected").all()]
    out: list[dict] = []
    for f in facts:
        if f.category not in ("experience", "education"):
            continue
        s = parse_ym(f.value.get("start_date"), end=False)
        e = parse_ym(f.value.get("end_date"), end=True) if f.value.get("end_date") else None
        if s and e and month_index(e) < month_index(s):
            out.append({"kind": "date_order", "fact_ids": [f.id],
                        "detail": f"'{f.key}' ends ({f.value.get('end_date')}) before it starts "
                                  f"({f.value.get('start_date')})."})
        for k in ("start_date", "end_date"):
            raw = f.value.get(k)
            if raw and parse_ym(raw) is None:
                out.append({"kind": "unparseable_date", "fact_ids": [f.id],
                            "detail": f"'{f.key}': could not understand {k} '{raw}'."})
    exps = [f for f in facts if f.category == "experience"]
    for i, a in enumerate(exps):
        ra = _range(a.value)
        for b in exps[i + 1:]:
            rb = _range(b.value)
            if not ra or not rb or ra[1] < ra[0] or rb[1] < rb[0]:
                continue
            overlap = min(ra[1], rb[1]) - max(ra[0], rb[0]) + 1
            if overlap > 2:
                out.append({"kind": "overlap", "fact_ids": [a.id, b.id],
                            "detail": f"'{a.key}' and '{b.key}' overlap by {overlap} months; "
                                      "confirm they were concurrent."})
    texts = {f.id: fact_text(f.category, f.value) for f in facts if f.category != "skill"
             and f.category != "contact"}
    for f in facts:
        if f.category != "skill" or not f.value.get("name"):
            continue
        pat = re.compile(r"(?<![\w+#])" + re.escape(f.value["name"]) + r"(?![\w+#])", re.I)
        if not any(pat.search(t) for t in texts.values()):
            out.append({"kind": "skill_no_evidence", "fact_ids": [f.id],
                        "detail": f"Skill '{f.value['name']}' is not supported by any experience,"
                                  " project, certification or education entry."})
    return out


def skill_support(db: Session, p: CandidateProfile, skill_fact: ProfileFact) -> list[str]:
    name = skill_fact.value.get("name") or ""
    pat = re.compile(r"(?<![\w+#])" + re.escape(name) + r"(?![\w+#])", re.I)
    return [f.id for f in confirmed_facts(db, p)
            if f.category in ("experience", "project", "certification", "education",
                              "publication") and pat.search(fact_text(f.category, f.value))]


# ------------------------------------------------------------------ export / import
def export_profile(db: Session, p: CandidateProfile) -> dict:
    return {"format": "careerpilot-profile", "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_dict(db, p, full=False) | {"id": None},
            "facts": [{"category": f.category, "key": f.key, "value": f.value,
                       "status": f.status, "confidence": f.confidence,
                       "source_location": f.source_location}
                      for f in _fact_query(db, p).order_by(ProfileFact.created_at).all()]}


def import_profile(db: Session, p: CandidateProfile, payload: dict, mode: str = "merge",
                   actor: str | None = None) -> dict:
    if payload.get("format") != "careerpilot-profile" or not isinstance(payload.get("facts"),
                                                                       list):
        raise ProfileError(422, "Not a CareerPilot profile export", "invalid_export")
    if mode not in ("merge", "replace"):
        raise ProfileError(422, "mode must be 'merge' or 'replace'")
    if mode == "replace":
        for f in _fact_query(db, p).all():
            f.deleted_at = utcnow()
            row = _row_for(db, f)
            if row is not None:
                row.deleted_at = utcnow()
        db.flush()
    existing = {(f.category, f.key.lower(), repr(sorted(f.value.items(), key=str)))
                for f in _fact_query(db, p).all()}
    imported = skipped = 0
    for it in payload["facts"]:
        try:
            cat = it["category"]
            val = normalize_value(cat, it.get("value") or {})
            status = it.get("status", "proposed")
            if status not in ("proposed", "confirmed", "rejected"):
                status = "proposed"
            if status == "confirmed" and missing_required(cat, val):
                status = "proposed"
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        sig = (cat, fact_key(cat, val).lower(), repr(sorted(val.items(), key=str)))
        if sig in existing:
            skipped += 1
            continue
        existing.add(sig)
        f = create_fact(db, p, cat, val, status=status, confidence=it.get("confidence"),
                        source_location=it.get("source_location") or "import")
        if status == "confirmed":
            materialize(db, p, f, create=True)
        imported += 1
    prof = payload.get("profile") or {}
    update_profile(db, p, {k: prof[k] for k in (*_PROFILE_FIELDS, "links", "preferences")
                           if k in prof and prof[k] not in (None, "", {})})
    bump_version(db, p)
    audit(db, "profile.import", actor=actor, subject_type="profile", subject_id=p.id,
          detail={"imported": imported, "skipped": skipped, "mode": mode})
    return {"imported": imported, "skipped": skipped}
