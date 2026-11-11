"""Document upload / parse endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import Document, ParseRun, User
from ...db.session import get_db
from ...documents import ingest
from ...documents import profile_service as ps
from ...documents.errors import DocumentError
from ...documents.parsers import MAX_BYTES

router = APIRouter(tags=["documents"])


def _doc(db: Session, doc_id: str) -> Document:
    d = db.get(Document, doc_id)
    if not d or d.deleted_at is not None:
        raise HTTPException(404, "Document not found")
    return d


@router.post("/documents", status_code=201)
async def upload(file: UploadFile = File(...), kind: str = Form("resume"),
                 use_llm: bool = Form(False), db: Session = Depends(get_db),
                 _: User = Depends(current_user)):
    data = await file.read(MAX_BYTES + 1)
    try:
        doc, run = ingest.ingest_upload(db, ps.get_profile(db), file.filename or "upload",
                                        data, kind, use_llm)
    except DocumentError as e:
        status = 413 if e.code == "too_large" else 422
        return JSONResponse(status_code=status, content={"detail": e.message, "code": e.code})
    return {"document": ingest.document_dict(doc), "parse_run": ingest.parse_run_dict(db, run)}


@router.get("/documents")
def list_documents(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(Document).filter(Document.deleted_at.is_(None))
    return {"items": [ingest.document_dict(d) for d in
                      q.order_by(Document.created_at.desc()).offset(offset).limit(limit)],
            "total": q.count()}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return ingest.document_dict(_doc(db, doc_id))


@router.get("/documents/{doc_id}/download")
def download(doc_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = _doc(db, doc_id)
    return FileResponse(d.storage_path, media_type=d.mime or "application/octet-stream",
                        filename=d.filename)


@router.get("/documents/{doc_id}/parse-runs")
def parse_runs(doc_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _doc(db, doc_id)
    rows = db.query(ParseRun).filter(ParseRun.document_id == doc_id).order_by(
        ParseRun.created_at.desc()).all()
    return {"items": [ingest.parse_run_dict(db, r, with_facts=False) for r in rows],
            "total": len(rows)}


@router.post("/documents/{doc_id}/parse")
def reparse(doc_id: str, use_llm: bool = Query(False), db: Session = Depends(get_db),
            _: User = Depends(current_user)):
    d = _doc(db, doc_id)
    run = ingest.run_parse(db, ps.get_profile(db), d, use_llm=use_llm)
    return ingest.parse_run_dict(db, run)


@router.get("/parse-runs/{run_id}")
def get_parse_run(run_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    r = db.get(ParseRun, run_id)
    if not r or r.deleted_at is not None:
        raise HTTPException(404, "Parse run not found")
    return ingest.parse_run_dict(db, r)
