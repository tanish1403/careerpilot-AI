"""Resume Studio endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import Job, ResumeVersion, User
from ...db.session import get_db
from ...documents import profile_service as ps
from ...resume_engine import cover_letter as cl
from ...resume_engine import service as svc
from ...resume_engine import versions as vs
from ...resume_engine.templates import sync_templates, template_dict
from ._laneb import error_response

router = APIRouter(tags=["resumes"])
MAX_JD = 60000


def _version(db: Session, rid: str) -> ResumeVersion:
    v = db.get(ResumeVersion, rid)
    if not v or v.deleted_at is not None:
        raise HTTPException(404, "Resume version not found")
    return v


def _job(db: Session, job_id: str) -> Job:
    j = db.get(Job, job_id)
    if not j or j.deleted_at is not None:
        raise HTTPException(404, "Job not found")
    return j


@router.get("/resume-templates")
def templates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = sync_templates(db)
    return {"items": [template_dict(r) for r in rows], "total": len(rows)}


@router.get("/resumes")
def list_resumes(job_id: str | None = None, limit: int = Query(50, ge=1, le=500),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                 _: User = Depends(current_user)):
    p = ps.get_profile(db)
    q = db.query(ResumeVersion).filter(ResumeVersion.profile_id == p.id,
                                       ResumeVersion.deleted_at.is_(None))
    if job_id:
        q = q.filter(ResumeVersion.job_id == job_id)
    total = q.count()
    rows = q.order_by(ResumeVersion.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [vs.version_dict(db, v, p, full=False) for v in rows], "total": total}


@router.post("/resumes/generate", status_code=201)
def generate(body: dict[str, Any] = Body(default_factory=dict), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    p = ps.get_profile(db)
    jd = body.get("job_description")
    if jd is not None and (not isinstance(jd, str) or len(jd) > MAX_JD):
        raise HTTPException(422, f"job_description must be text up to {MAX_JD} characters")
    job = _job(db, body["job_id"]) if body.get("job_id") else None
    try:
        v = svc.generate(db, p, job=job, job_description=jd, template_id=body.get("template_id"),
                         label=body.get("label"), compile_pdf=body.get("compile", True) is not False,
                         use_llm=body.get("use_llm") is True, actor=user.username)
    except ps.ProfileError as e:
        return error_response(e)
    return vs.version_dict(db, v, p)


@router.get("/resumes/{rid}")
def get_resume(rid: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return vs.version_dict(db, _version(db, rid), ps.get_profile(db))


@router.put("/resumes/{rid}/source", status_code=201)
def put_source(rid: str, body: dict[str, Any] = Body(...), compile: bool = Query(False),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    src = body.get("latex_source")
    if not isinstance(src, str) or not src.strip():
        raise HTTPException(422, "latex_source is required")
    p = ps.get_profile(db)
    try:
        nv = svc.edit_source(db, p, _version(db, rid), src, label=body.get("label"),
                             compile_pdf=compile, actor=user.username)
    except ps.ProfileError as e:
        return error_response(e)
    return vs.version_dict(db, nv, p)


@router.post("/resumes/{rid}/compile")
def compile_(rid: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    v = svc.compile_version(db, _version(db, rid))
    return vs.version_dict(db, v, ps.get_profile(db))


@router.get("/resumes/{rid}/pdf")
def pdf(rid: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    v = _version(db, rid)
    if not v.pdf_path or not Path(v.pdf_path).exists():
        raise HTTPException(404, "No compiled PDF for this version; POST /compile first")
    return FileResponse(v.pdf_path, media_type="application/pdf",
                        filename=f"resume-v{v.version_no}.pdf")


@router.get("/resumes/{rid}/tex")
def tex(rid: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    v = _version(db, rid)
    return PlainTextResponse(v.latex_source, headers={
        "Content-Disposition": f'attachment; filename="resume-v{v.version_no}.tex"'})


@router.get("/resumes/{rid}/diff")
def diff(rid: str, against: str = Query("original"), db: Session = Depends(get_db),
         _: User = Depends(current_user)):
    v = _version(db, rid)
    other = vs.root_of(db, v) if against == "original" else _version(db, against)
    return vs.diff_sources(other.latex_source, v.latex_source,
                           [c.text for c in vs.claims_of(db, other)],
                           [c.text for c in vs.claims_of(db, v)]) | {
        "against": other.id, "version": v.id}


@router.post("/resumes/{rid}/restore", status_code=201)
def restore(rid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = ps.get_profile(db)
    return vs.version_dict(db, svc.restore(db, p, _version(db, rid), user.username), p)


@router.post("/resumes/{rid}/claims/{claim_id}/confirm")
def confirm_claim(rid: str, claim_id: str, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    try:
        c = svc.confirm_claim(db, _version(db, rid), claim_id, user.username)
    except ps.ProfileError as e:
        return error_response(e)
    return vs.claim_dict(c)


@router.post("/cover-letters/generate")
def cover_letter(body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
                 _: User = Depends(current_user)):
    if not body.get("job_id"):
        raise HTTPException(422, "job_id is required")
    job = _job(db, body["job_id"])
    resume = _version(db, body["resume_id"]) if body.get("resume_id") else None
    return cl.generate_cover_letter(db, ps.get_profile(db), job, resume=resume,
                                    rewrite=svc.REWORD_FN if body.get("use_llm") is True
                                    else None)


_ = JSONResponse
