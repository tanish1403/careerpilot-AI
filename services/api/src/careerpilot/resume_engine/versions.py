"""Resume versioning: every change is a NEW ResumeVersion; nothing is overwritten."""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.base import new_id
from ..db.models import CandidateProfile, ResumeClaim, ResumeVersion
from .render import MARK, ClaimDraft, parse_source_claims

_LINE_KINDS = (r"\item", r"\cpentry", r"\cpskills", r"\cpsummary")


def pdf_path_for(version_id: str) -> Path:
    return get_settings().artifacts_dir / "resumes" / f"{version_id}.pdf"


def next_version_no(db: Session, profile: CandidateProfile, job_id: str | None) -> int:
    q = db.query(ResumeVersion.version_no).filter(
        ResumeVersion.profile_id == profile.id, ResumeVersion.deleted_at.is_(None))
    q = q.filter(ResumeVersion.job_id == job_id) if job_id else q.filter(
        ResumeVersion.job_id.is_(None))
    return max([r[0] or 0 for r in q.all()] or [0]) + 1


def latest_in_scope(db: Session, profile: CandidateProfile, job_id: str | None
                    ) -> ResumeVersion | None:
    q = db.query(ResumeVersion).filter(ResumeVersion.profile_id == profile.id,
                                       ResumeVersion.deleted_at.is_(None))
    q = q.filter(ResumeVersion.job_id == job_id) if job_id else q.filter(
        ResumeVersion.job_id.is_(None))
    return q.order_by(ResumeVersion.version_no.desc()).first()


def root_of(db: Session, v: ResumeVersion) -> ResumeVersion:
    seen = {v.id}
    cur = v
    while cur.parent_version_id and cur.parent_version_id not in seen:
        parent = db.get(ResumeVersion, cur.parent_version_id)
        if parent is None:
            break
        seen.add(parent.id)
        cur = parent
    return cur


def claims_of(db: Session, v: ResumeVersion) -> list[ResumeClaim]:
    return db.query(ResumeClaim).filter(ResumeClaim.resume_version_id == v.id,
                                        ResumeClaim.deleted_at.is_(None)
                                        ).order_by(ResumeClaim.created_at, ResumeClaim.id).all()


def claim_dict(c: ResumeClaim) -> dict:
    return {"id": c.id, "text": c.text, "evidence_ids": c.evidence_ids or [],
            "needs_confirmation": bool(c.needs_confirmation)}


def create_version(db: Session, profile: CandidateProfile, *, source: str,
                   claims: list[ClaimDraft], job_id: str | None, template_id: str | None,
                   parent: ResumeVersion | None, label: str | None,
                   report: dict | None = None, pdf_from: Path | None = None
                   ) -> ResumeVersion:
    v = ResumeVersion(workspace_id="default", profile_id=profile.id, job_id=job_id,
                      template_id=template_id,
                      parent_version_id=parent.id if parent else None,
                      version_no=next_version_no(db, profile, job_id), latex_source=source,
                      validation_report=report or {}, profile_version=profile.version,
                      label=(label or None) and label[:200])
    db.add(v)
    db.flush()
    for c in claims:
        db.add(ResumeClaim(id=c.id, workspace_id="default", resume_version_id=v.id,
                           text=c.text, evidence_ids=list(c.evidence_ids),
                           needs_confirmation=bool(c.needs_confirmation)))
    if pdf_from and pdf_from.exists():
        dest = pdf_path_for(v.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf_from.read_bytes())
        v.pdf_path = str(dest)
    db.flush()
    return v


def version_dict(db: Session, v: ResumeVersion, profile: CandidateProfile | None = None, *,
                 full: bool = True) -> dict:
    claims = claims_of(db, v)
    d: dict[str, Any] = {
        "id": v.id, "version_no": v.version_no, "label": v.label, "job_id": v.job_id,
        "template_id": v.template_id, "parent_version_id": v.parent_version_id,
        "profile_version": v.profile_version,
        "pdf_available": bool(v.pdf_path and Path(v.pdf_path).exists()),
        "validation_report": v.validation_report or {},
        "needs_confirmation_count": sum(1 for c in claims if c.needs_confirmation),
        "created_at": v.created_at,
        "stale": bool(profile and profile.version != v.profile_version)}
    if full:
        d["latex_source"] = v.latex_source
        d["claims"] = [claim_dict(c) for c in claims]
    return d


def reclaim_source(source: str, parent_claims: list[ResumeClaim], *, keep_flags: bool
                   ) -> tuple[str, list[ClaimDraft]]:
    """Give every claim-bearing line a fresh claim id for a NEW version. Known lines inherit the
    parent's evidence; changed or unknown lines are flagged needs_confirmation."""
    by_id = {c.id: c for c in parent_claims}
    out_lines: list[str] = []
    drafts: list[ClaimDraft] = []
    parsed = iter(parse_source_claims(source))
    for raw in source.splitlines():
        s = raw.strip()
        if not s.startswith(_LINE_KINDS):
            out_lines.append(raw)
            continue
        old_id, _kind, plain = next(parsed)
        parent = by_id.get(old_id) if old_id else None
        new = new_id()
        if parent is not None:
            changed = parent.text != plain
            needs = bool(parent.needs_confirmation) if (keep_flags and not changed) else \
                (bool(parent.needs_confirmation) or changed)
            if not parent.evidence_ids:
                needs = True
            drafts.append(ClaimDraft(new, plain, list(parent.evidence_ids or []), needs))
        else:
            drafts.append(ClaimDraft(new, plain, [], True))
        out_lines.append(MARK.sub("", raw).rstrip() + f" % cp:claim={new}")
    trailing = "\n" if source.endswith("\n") else ""
    return "\n".join(out_lines) + trailing, drafts


def diff_sources(old: str, new: str, old_claims: list[str], new_claims: list[str]) -> dict:
    a = [MARK.sub("", x) for x in old.splitlines()]
    b = [MARK.sub("", x) for x in new.splitlines()]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks: list[dict] = []
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ctx = a[i1:i2]
            if len(ctx) > 4:
                hunks.append({"op": "equal", "text": "\n".join(ctx[:2])})
                hunks.append({"op": "skip", "text": f"... {len(ctx) - 4} unchanged lines ..."})
                hunks.append({"op": "equal", "text": "\n".join(ctx[-2:])})
            elif ctx:
                hunks.append({"op": "equal", "text": "\n".join(ctx)})
            continue
        if i2 > i1:
            removed += i2 - i1
            hunks.append({"op": "remove", "text": "\n".join(a[i1:i2])})
        if j2 > j1:
            added += j2 - j1
            hunks.append({"op": "add", "text": "\n".join(b[j1:j2])})
    oc, nc = set(old_claims), set(new_claims)
    return {"hunks": hunks, "claims_added": sorted(nc - oc), "claims_removed": sorted(oc - nc),
            "summary": f"{added} line(s) added, {removed} removed; "
                       f"{len(nc - oc)} claim(s) added, {len(oc - nc)} removed"}


_ = re
