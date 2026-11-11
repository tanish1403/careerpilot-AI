"""Versioned, validated matching configuration stored in Setting key 'matching.config'."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import Setting
from .taxonomy import taxonomy_version

SETTING_KEY = "matching.config"
ALGO_VERSION = "1"
DEFAULT_WEIGHTS = {"technical_skills": 0.25, "experience": 0.20, "projects": 0.15, "education": 0.10,
                   "domain": 0.10, "role_alignment": 0.10, "location": 0.05, "freshness": 0.05}
DEFAULT_PRIORITY_WEIGHTS = {"fit": 0.50, "freshness": 0.15, "urgency": 0.10, "preference_alignment": 0.10,
                            "effort": 0.10, "goals": 0.05}
TOLERANCE = 1e-6
DISCLAIMER = ("This score is decision support based on the evidence in your profile and the job text. "
              "It is NOT a probability of being interviewed or selected, and unknown requirements are "
              "never counted as satisfied.")


@dataclass(frozen=True)
class MatchConfig:
    weights: dict[str, float]
    priority_weights: dict[str, float]
    version: str

    def to_dict(self) -> dict:
        return {"weights": dict(self.weights), "priority_weights": dict(self.priority_weights),
                "version": self.version}


def _validate(w: object, names: dict[str, float], label: str) -> dict[str, float]:
    if not isinstance(w, dict):
        raise ValueError(f"{label} must be an object")
    if set(w) != set(names):
        raise ValueError(f"{label} must have exactly the keys: {', '.join(names)}")
    out: dict[str, float] = {}
    for k, v in w.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{label}.{k} must be a number")
        if not 0 <= float(v) <= 1:
            raise ValueError(f"{label}.{k} must be between 0 and 1")
        out[k] = float(v)
    if abs(sum(out.values()) - 1.0) > 1e-4:
        raise ValueError(f"{label} must sum to 1 (got {sum(out.values()):.4f})")
    return {k: out[k] for k in names}


def validate_weights(w: object) -> dict[str, float]:
    return _validate(w, DEFAULT_WEIGHTS, "weights")


def validate_priority_weights(w: object) -> dict[str, float]:
    return _validate(w, DEFAULT_PRIORITY_WEIGHTS, "priority_weights")


def compute_version(weights: dict, priority: dict) -> str:
    blob = json.dumps({"w": {k: round(v, 6) for k, v in sorted(weights.items())},
                       "p": {k: round(v, 6) for k, v in sorted(priority.items())},
                       "algo": ALGO_VERSION, "taxonomy": taxonomy_version()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def make_config(weights: dict | None = None, priority: dict | None = None) -> MatchConfig:
    w = validate_weights(weights or DEFAULT_WEIGHTS)
    p = validate_priority_weights(priority or DEFAULT_PRIORITY_WEIGHTS)
    return MatchConfig(w, p, compute_version(w, p))


def load_config(db: Session) -> MatchConfig:
    row = db.get(Setting, SETTING_KEY)
    if row is not None and isinstance(row.value, dict):
        try:
            return make_config(row.value.get("weights"), row.value.get("priority_weights"))
        except ValueError:
            pass            # corrupted setting: fall back to defaults rather than failing scoring
    return make_config()


def save_config(db: Session, weights: dict, priority: dict | None = None) -> MatchConfig:
    cfg = make_config(weights, priority if priority is not None else load_config(db).priority_weights)
    row = db.get(Setting, SETTING_KEY)
    value = cfg.to_dict()
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    db.flush()
    return cfg
