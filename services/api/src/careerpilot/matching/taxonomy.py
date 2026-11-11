"""Skill / domain / role-family taxonomy with synonyms (js -> javascript, k8s -> kubernetes)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "data" / "taxonomy.json"
_WORD_BEFORE = r"(?<![A-Za-z0-9_])"
_WORD_AFTER = r"(?![A-Za-z0-9_+#])"
_NO_CANONICAL = {"go", "c", "r"}   # too ambiguous as bare words


def _collapse(s: str) -> str:
    return re.sub(r"[\s\-]+", " ", s.strip().lower())


def _alias_regex(alias: str) -> str:
    return r"[\s\-]+".join(re.escape(p) for p in alias.split(" "))


class _Matcher:
    def __init__(self, table: dict[str, list[str]], *, include_canonical: bool = True) -> None:
        self.alias_to_name: dict[str, str] = {}
        self.raw: list[tuple[re.Pattern[str], str]] = []
        for name, aliases in table.items():
            plain = ([name] if include_canonical and name not in _NO_CANONICAL else []) + [a for a in aliases if not a.startswith("re:")]
            for a in plain:
                self.alias_to_name[_collapse(a)] = name
            for a in aliases:
                if a.startswith("re:"):
                    self.raw.append((re.compile(a[3:]), name))
        keys = sorted(self.alias_to_name, key=len, reverse=True)
        self.rx = re.compile(_WORD_BEFORE + "(?:" + "|".join(_alias_regex(k) for k in keys) + ")"
                             + _WORD_AFTER, re.I)

    def find(self, text: str) -> list[str]:
        hits: list[tuple[int, str]] = []
        for m in self.rx.finditer(text or ""):
            hits.append((m.start(), self.alias_to_name[_collapse(m.group(0))]))
        for rx, name in self.raw:
            for m in rx.finditer(text or ""):
                hits.append((m.start(), name))
        seen: list[str] = []
        for _, n in sorted(hits):
            if n not in seen:
                seen.append(n)
        return seen


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _skills() -> _Matcher:
    return _Matcher(_data()["skills"])


@lru_cache(maxsize=1)
def _domains() -> _Matcher:
    return _Matcher(_data()["domains"], include_canonical=False)


@lru_cache(maxsize=1)
def _roles() -> _Matcher:
    return _Matcher(_data()["role_families"], include_canonical=False)


def taxonomy_version() -> str:
    return str(_data().get("version", "1"))


def find_skills(text: str) -> list[str]:
    return _skills().find(text)


def canonical_skill(name: str) -> str:
    """Canonical skill name for a free-text skill label (unknown names are just lower-cased)."""
    key = _collapse(name or "")
    found = _skills().alias_to_name.get(key)
    if found:
        return found
    hits = _skills().find(name or "")
    if len(hits) == 1 and _collapse(name) == _collapse(hits[0]):
        return hits[0]
    return key


def find_domains(text: str) -> list[str]:
    return _domains().find(text)


def role_families(text: str) -> list[str]:
    return _roles().find(text)
