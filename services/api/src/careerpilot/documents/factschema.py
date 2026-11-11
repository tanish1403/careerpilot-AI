"""Fact categories, value normalisation and the mapping onto typed profile rows."""
from __future__ import annotations

from typing import Any

from .dates import normalize_date

CATEGORIES = ("experience", "education", "skill", "project", "publication", "certification",
              "contact", "summary", "other")
ITEM_CATEGORIES = ("experience", "education", "skill", "project", "publication",
                   "certification")
REQUIRED = {"experience": ("company", "title"), "education": ("institution",),
            "skill": ("name",), "project": ("name",), "publication": ("title",),
            "certification": ("name",), "summary": ("text",)}
_STR, _DATE, _LIST, _NUM, _DICT = "str", "date", "list", "num", "dict"
FIELDS: dict[str, dict[str, str]] = {
    "experience": {"company": _STR, "title": _STR, "location": _STR, "start_date": _DATE,
                   "end_date": _DATE, "bullets": _LIST},
    "education": {"institution": _STR, "degree": _STR, "field": _STR, "start_date": _DATE,
                  "end_date": _DATE, "grade": _STR},
    "skill": {"name": _STR, "category": _STR, "level": _STR, "years": _NUM},
    "project": {"name": _STR, "description": _STR, "url": _STR, "technologies": _LIST,
                "bullets": _LIST},
    "publication": {"title": _STR, "venue": _STR, "year": _STR, "url": _STR},
    "certification": {"name": _STR, "issuer": _STR, "date": _DATE, "url": _STR},
    "contact": {"full_name": _STR, "headline": _STR, "email": _STR, "phone": _STR,
                "location": _STR, "links": _DICT},
    "summary": {"text": _STR},
}
_MAX = {"title": 400, "description": 4000, "text": 4000, "url": 500, "name": 300,
        "headline": 300}
_ARRAY_MAX = 40


def _s(v: Any, n: int) -> str | None:
    if v is None:
        return None
    t = " ".join(str(v).split())
    return t[:n] or None


def normalize_value(category: str, value: dict) -> dict:
    """Validate/normalise a fact value. Unknown keys are dropped (except for 'other')."""
    if not isinstance(value, dict):
        raise ValueError("value must be an object")
    if category not in FIELDS:
        return {str(k)[:60]: v for k, v in list(value.items())[:30]}
    out: dict[str, Any] = {}
    for k, kind in FIELDS[category].items():
        if k not in value:
            continue
        v = value[k]
        if kind == _STR:
            out[k] = _s(v, _MAX.get(k, 200))
        elif kind == _DATE:
            raw = _s(v, 40)
            out[k] = (normalize_date(raw) or raw) if raw else None
        elif kind == _LIST:
            items = v if isinstance(v, list) else ([] if v is None else [v])
            out[k] = [t for t in (_s(i, 1200 if k == "bullets" else 100) for i in items) if t
                      ][:_ARRAY_MAX]
        elif kind == _NUM:
            try:
                out[k] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError) as e:
                raise ValueError(f"{k} must be a number") from e
        elif kind == _DICT:
            out[k] = {str(a)[:40]: str(b)[:500] for a, b in (v or {}).items()
                      if isinstance(v, dict) and b}
    return out


def missing_required(category: str, value: dict) -> list[str]:
    return [f for f in REQUIRED.get(category, ()) if not value.get(f)]


def fact_key(category: str, v: dict) -> str:
    g = lambda k: (v.get(k) or "").strip()  # noqa: E731
    if category == "experience":
        return f"{g('title')} @ {g('company')}".strip(" @")
    if category == "education":
        return f"{g('degree')} - {g('institution')}".strip(" -")
    if category in ("skill", "project", "certification"):
        return g("name")
    if category == "publication":
        return g("title")[:200]
    if category == "contact":
        return "contact"
    if category == "summary":
        return "summary"
    return str(v.get("key") or "other")[:200]


def fact_text(category: str, v: dict) -> str:
    """Flatten a fact value to searchable text (used for skill-evidence checks)."""
    parts: list[str] = []
    for val in v.values():
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
        elif isinstance(val, dict):
            parts.extend(str(x) for x in val.values())
        elif val is not None:
            parts.append(str(val))
    return " \n ".join(parts)
