"""Draft answers from CONFIRMED profile facts only. Anything else is escalated."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..core.enums import VerificationStatus
from ..db.models import ProfileFact
from .classifier import Classification, classify_question


@dataclass
class Draft:
    answer: str | None
    evidence_ids: list[str] = field(default_factory=list)
    sensitive: bool = False
    needs_user: bool = True
    category: str = "needs_user"
    source: str = "none"


def _confirmed(db: Session, category: str) -> list[ProfileFact]:
    return (db.query(ProfileFact)
            .filter(ProfileFact.category == category,
                    ProfileFact.status == VerificationStatus.CONFIRMED.value,
                    ProfileFact.deleted_at.is_(None))
            .order_by(ProfileFact.updated_at.desc()).all())


def _contact(db: Session, key: str) -> tuple[str | None, str | None]:
    """Latest confirmed contact fact carrying `key` -> (value, fact_id)."""
    for f in _confirmed(db, "contact"):
        v = (f.value or {}).get(key)
        if isinstance(v, str) and v.strip():
            return v.strip(), f.id
    return None, None


def _link(db: Session, name: str) -> tuple[str | None, str | None]:
    for f in _confirmed(db, "contact"):
        links = (f.value or {}).get("links") or {}
        if isinstance(links, dict):
            for k, v in links.items():
                if name in str(k).lower() and isinstance(v, str) and v.strip():
                    return v.strip(), f.id
    return None, None


def _current_experience(db: Session) -> ProfileFact | None:
    cur = [f for f in _confirmed(db, "experience")
           if not (f.value or {}).get("end_date")
           or str((f.value or {}).get("end_date")).lower() in ("present", "current")]
    cur.sort(key=lambda f: str((f.value or {}).get("start_date") or ""), reverse=True)
    return cur[0] if cur else None


def _latest_education(db: Session) -> ProfileFact | None:
    eds = _confirmed(db, "education")
    eds.sort(key=lambda f: str((f.value or {}).get("end_date") or "9999"), reverse=True)
    return eds[0] if eds else None


def _lookup(db: Session, topic: str) -> tuple[str | None, list[str]]:
    if topic in ("first_name", "last_name", "full_name"):
        name, fid = _contact(db, "full_name")
        if not name:
            return None, []
        parts = name.split()
        val = {"full_name": name, "first_name": parts[0],
               "last_name": " ".join(parts[1:]) if len(parts) > 1 else None}[topic]
        return val, [fid] if val and fid else []
    if topic in ("email", "phone", "location", "headline"):
        v, fid = _contact(db, topic)
        return v, [fid] if v else []
    if topic in ("linkedin", "github"):
        v, fid = _link(db, topic)
        return v, [fid] if v else []
    if topic == "website":
        for name in ("portfolio", "website", "personal", "site", "blog"):
            v, fid = _link(db, name)
            if v:
                return v, [fid]
        return None, []
    if topic in ("current_company", "current_title"):
        f = _current_experience(db)
        v = (f.value or {}).get("company" if topic == "current_company" else "title") if f else None
        return (v, [f.id]) if v else (None, [])
    if topic in ("school", "degree"):
        f = _latest_education(db)
        v = (f.value or {}).get("institution" if topic == "school" else "degree") if f else None
        return (v, [f.id]) if v else (None, [])
    return None, []


def draft_answer(db: Session, question: str, cls: Classification | None = None) -> Draft:
    cls = cls or classify_question(question)
    if cls.sensitive:
        return Draft(None, [], True, True, cls.category, "sensitive_policy")
    if cls.topic:
        val, ev = _lookup(db, cls.topic)
        if val and ev:
            return Draft(val, ev, False, False, cls.category, "confirmed_fact")
        return Draft(None, [], False, True, cls.category, "no_confirmed_fact")
    return Draft(None, [], False, True, cls.category, "unmatched")
