"""Orchestration for Resume Studio: generate, edit, compile+validate, restore, confirm claims."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.audit import audit
from ..db.models import CandidateProfile, Job, ResumeClaim, ResumeVersion
from ..documents.profile_service import ProfileError
from . import compiler, validator
from .latex import find_forbidden
from .model import build_model
from .render import fill_template, render_body
from .tailor import RewordFn, check_integrity, jd_text_from, tailor
from .templates import resolve
from .versions import (claims_of, create_version, latest_in_scope, pdf_path_for, reclaim_source)

# Lane D may set a gateway-backed callable (bullet, wrapped_jd) -> str|None here.
REWORD_FN: RewordFn | None = None


def _err(status: int, detail: str, code: str | None = None) -> ProfileError:
    return ProfileError(status, detail, code)


def generate(db: Session, profile: CandidateProfile, *, job: Job | None = None,
             job_description: str | None = None, template_id: str | None = None,
             label: str | None = None, compile_pdf: bool = True, use_llm: bool = False,
             actor: str | None = None) -> ResumeVersion:
    model = build_model(db, profile)
    if model.is_empty():
        raise _err(422, "No confirmed facts yet. Confirm experience, education or skills in "
                        "your profile before generating a resume.", "no_confirmed_facts")
    tpl = resolve(db, template_id)
    if tpl is None:
        raise _err(404, "Unknown template")
    jd = (jd_text_from(job.title, job.company_name, job.description, job.requirements)
          if job else "") or (job_description or "")
    report: dict = {}
    final = model
    if jd.strip():
        final, trep = tailor(model, jd[:60000], reword=REWORD_FN if use_llm else None)
        problems = check_integrity(model, final)
        if problems:  # defence in depth: never emit a tailored resume that breaks integrity
            raise _err(500, "Tailoring integrity check failed: " + "; ".join(problems[:3]),
                       "integrity_violation")
        report["tailoring"] = trep
    body, drafts = render_body(final)
    source = fill_template(tpl.latex_source, final, body)
    bad = find_forbidden(source)
    if bad:
        raise _err(500, "Generated source failed safety scan: " + "; ".join(bad[:3]),
                   "unsafe_latex")
    report["claims"] = {"total": len(drafts),
                        "needs_confirmation": sum(1 for d in drafts if d.needs_confirmation)}
    job_id = job.id if job else None
    v = create_version(db, profile, source=source, claims=drafts, job_id=job_id,
                       template_id=tpl.id, parent=latest_in_scope(db, profile, job_id),
                       label=label or ("Tailored resume" if jd.strip() else "Master resume"),
                       report=report)
    audit(db, "resume.generate", actor=actor, subject_type="resume", subject_id=v.id,
          detail={"job_id": job_id, "template": tpl.name, "tailored": bool(jd.strip())})
    if compile_pdf:
        compile_version(db, v)
    return v


def compile_version(db: Session, v: ResumeVersion) -> ResumeVersion:
    report = dict(v.validation_report or {})
    bad = find_forbidden(v.latex_source)
    if bad:
        report["compile"] = {"ok": False, "error": "Unsafe LaTeX: " + "; ".join(bad[:5])}
        report["ok"] = False
        v.validation_report = report
        return v
    out = pdf_path_for(v.id)
    res = compiler.compile_latex(v.latex_source, out)
    report["compile"] = {"ok": res.ok, "error": res.error, "log_excerpt": res.log_excerpt,
                         "duration_s": round(res.duration_s, 2), "timed_out": res.timed_out}
    if res.ok:
        v.pdf_path = str(out)
        report["pdf"] = validator.validate_pdf(out, v.latex_source, res.warnings)
        report["ok"] = bool(report["pdf"]["ok"])
    else:
        report.pop("pdf", None)
        report["ok"] = False
    v.validation_report = report
    db.flush()
    return v


def edit_source(db: Session, profile: CandidateProfile, v: ResumeVersion, source: str, *,
                label: str | None = None, compile_pdf: bool = False,
                actor: str | None = None) -> ResumeVersion:
    bad = find_forbidden(source)
    if bad:
        raise _err(422, "LaTeX source rejected: " + "; ".join(bad[:5]), "unsafe_latex")
    new_source, drafts = reclaim_source(source, claims_of(db, v), keep_flags=True)
    report = {"claims": {"total": len(drafts),
                         "needs_confirmation": sum(1 for d in drafts if d.needs_confirmation)},
              "edited_from": v.id}
    nv = create_version(db, profile, source=new_source, claims=drafts, job_id=v.job_id,
                        template_id=v.template_id, parent=v,
                        label=label or f"Edited from v{v.version_no}", report=report)
    audit(db, "resume.edit_source", actor=actor, subject_type="resume", subject_id=nv.id,
          detail={"parent": v.id})
    if compile_pdf:
        compile_version(db, nv)
    return nv


def restore(db: Session, profile: CandidateProfile, v: ResumeVersion, actor: str | None = None
            ) -> ResumeVersion:
    new_source, drafts = reclaim_source(v.latex_source, claims_of(db, v), keep_flags=True)
    latest = latest_in_scope(db, profile, v.job_id)
    old_pdf = pdf_path_for(v.id) if v.pdf_path else None
    nv = create_version(db, profile, source=new_source, claims=drafts, job_id=v.job_id,
                        template_id=v.template_id, parent=latest or v,
                        label=f"Restored from v{v.version_no}",
                        report={**{k: x for k, x in (v.validation_report or {}).items()
                                   if k in ("tailoring", "compile", "pdf", "ok")},
                                "claims": {"total": len(drafts), "needs_confirmation":
                                           sum(1 for d in drafts if d.needs_confirmation)},
                                "restored_from": v.id}, pdf_from=old_pdf)
    audit(db, "resume.restore", actor=actor, subject_type="resume", subject_id=nv.id,
          detail={"restored_from": v.id})
    return nv


def confirm_claim(db: Session, v: ResumeVersion, claim_id: str, actor: str | None = None
                  ) -> ResumeClaim:
    c = db.get(ResumeClaim, claim_id)
    if not c or c.resume_version_id != v.id or c.deleted_at is not None:
        raise _err(404, "Claim not found")
    c.needs_confirmation = False
    rep = dict(v.validation_report or {})
    if "claims" in rep:
        rep["claims"] = {**rep["claims"], "needs_confirmation": sum(
            1 for x in claims_of(db, v) if x.needs_confirmation)}
        v.validation_report = rep
    audit(db, "resume.claim_confirm", actor=actor, subject_type="claim", subject_id=c.id)
    db.flush()
    return c
