"""LaTeX template registry: files in templates/latex/*.tex mirrored into ResumeTemplate rows."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.models import ResumeTemplate

DESCRIPTIONS = {"classic": "Single column, serif, ATS-friendly (default).",
                "modern": "Single column, sans-serif with accent colour, ATS-friendly."}
DEFAULT = "classic"


def _files() -> dict[str, str]:
    d = Path(get_settings().templates_dir) / "latex"
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.tex"))}


def sync_templates(db: Session) -> list[ResumeTemplate]:
    rows = {r.name: r for r in db.query(ResumeTemplate).filter(
        ResumeTemplate.deleted_at.is_(None)).all()}
    for name, src in _files().items():
        r = rows.get(name)
        if r is None:
            r = ResumeTemplate(workspace_id="default", name=name, version="1", latex_source=src)
            db.add(r)
            rows[name] = r
        elif r.latex_source != src:
            r.latex_source = src
            r.version = str(int(r.version or "1") + 1) if (r.version or "1").isdigit() else "2"
    db.flush()
    return sorted(rows.values(), key=lambda r: r.name)


def template_dict(r: ResumeTemplate) -> dict:
    return {"id": r.id, "name": r.name, "version": r.version,
            "description": DESCRIPTIONS.get(r.name, ""), "ats_friendly": True,
            "single_column": True}


def resolve(db: Session, template_id: str | None) -> ResumeTemplate | None:
    rows = sync_templates(db)
    if not template_id:
        template_id = DEFAULT
    for r in rows:
        if r.id == template_id or r.name == template_id:
            return r
    return None
