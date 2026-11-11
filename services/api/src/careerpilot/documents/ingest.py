"""Upload -> store original -> parse -> extract -> PROPOSED facts (never confirmed)."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from ..core.audit import audit
from ..core.config import get_settings
from ..core.untrusted import injection_flags
from ..db.base import utcnow
from ..db.models import CandidateProfile, Document, ParseRun, ProfileFact
from . import profile_service as ps
from .errors import DocumentError
from .llm_extract import Extractor, LLMAssistedExtractor, RuleBasedExtractor
from .parsers import parse_bytes
from .storage import safe_filename, sha256_hex, store_original

# Lane D can register a callable(prompt)->str|list|dict here; used only when a request asks
# for LLM assistance explicitly (and the integrator has checked external-LLM consent).
LLM_CALLABLE: Callable[[str], object] | None = None
MIME = {"pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
        "rtf": "application/rtf", "tex": "application/x-tex", "html": "text/html",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword", "png": "image/png", "jpg": "image/jpeg"}


def document_dict(d: Document) -> dict:
    return {"id": d.id, "profile_id": d.profile_id, "filename": d.filename, "mime": d.mime,
            "sha256": d.sha256, "size_bytes": d.size_bytes, "kind": d.kind,
            "created_at": d.created_at}


def parse_run_dict(db: Session, r: ParseRun, with_facts: bool = True) -> dict:
    d = {"id": r.id, "document_id": r.document_id, "status": r.status, "parser": r.parser,
         "warnings": r.warnings or [], "error": r.error, "created_at": r.created_at}
    if with_facts:
        facts = db.query(ProfileFact).filter(ProfileFact.parse_run_id == r.id,
                                             ProfileFact.deleted_at.is_(None)
                                             ).order_by(ProfileFact.created_at).all()
        d["facts"] = [ps.fact_dict(f) for f in facts]
    return d


def pick_extractor(use_llm: bool) -> Extractor:
    if use_llm and LLM_CALLABLE is not None:
        return LLMAssistedExtractor(LLM_CALLABLE)  # type: ignore[arg-type]
    return RuleBasedExtractor()


def _norm(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


def run_parse(db: Session, profile: CandidateProfile, doc: Document, *, use_llm: bool = False,
              extractor: Extractor | None = None, parsed=None) -> ParseRun:
    """Parse the stored original of `doc` and propose facts. Never raises for parse problems;
    the ParseRun records status/error instead."""
    run = ParseRun(workspace_id=ps.WS, document_id=doc.id, status="running")
    db.add(run)
    db.flush()
    warnings: list[str] = []
    try:
        data = Path(doc.storage_path).read_bytes()
        parsed = parsed or parse_bytes(data, doc.filename)
        run.parser = parsed.parser
        warnings += parsed.warnings
        flags = injection_flags(parsed.text)
        if flags:
            warnings.append("Document contains instruction-like text (" + ", ".join(flags)
                            + "); treated as data only.")
        res = (extractor or pick_extractor(use_llm)).extract(parsed)
        warnings += res.warnings
        existing = {(f.category, _norm(f.key)) for f in ps._fact_query(db, profile).filter(
            ProfileFact.status != "proposed").all()}
        proposed_same_doc = {(f.category, _norm(f.key)) for f in ps._fact_query(db, profile)
                             .filter(ProfileFact.status == "proposed").all()}
        skipped = 0
        for pf in res.facts:
            sig = (pf.category, _norm(pf.key))
            if sig in existing or sig in proposed_same_doc:
                if pf.category not in ("contact", "summary") or sig in existing:
                    skipped += 1
                    continue
            ps.create_fact(db, profile, pf.category, pf.value, status="proposed",
                           confidence=pf.confidence, source_document_id=doc.id,
                           source_location=pf.source_location, parse_run_id=run.id)
            proposed_same_doc.add(sig)
        if skipped:
            warnings.append(f"{skipped} fact(s) already in your profile (or previously "
                            "reviewed) were not proposed again.")
        text_dir = get_settings().artifacts_dir / "parsed"
        text_dir.mkdir(parents=True, exist_ok=True)
        (text_dir / f"{run.id}.txt").write_text(parsed.text, encoding="utf-8")
        run.raw_text_ref = f"parsed/{run.id}.txt"
        run.status = "succeeded"
    except DocumentError as e:
        run.status = "failed"
        run.error = f"[{e.code}] {e.message}"
    except Exception as e:  # noqa: BLE001
        run.status = "failed"
        run.error = f"[internal_error] {type(e).__name__}"
    run.warnings = warnings
    audit(db, "document.parse", subject_type="document", subject_id=doc.id,
          detail={"status": run.status, "parser": run.parser})
    db.flush()
    return run


def ingest_upload(db: Session, profile: CandidateProfile, filename: str, data: bytes,
                  kind: str = "resume", use_llm: bool = False) -> tuple[Document, ParseRun]:
    """Validate (raises DocumentError for 422-class problems BEFORE storing anything), store the
    original immutably and parse it."""
    filename = safe_filename(filename)
    parsed = None
    try:
        parsed = parse_bytes(data, filename)  # pre-flight validation (reused below)
    except DocumentError as e:
        if e.rejects_upload or e.code == "too_large":
            raise
        # valid file we cannot read yet (e.g. scanned, OCR missing): keep it, fail the run
    sha, path = store_original(data, filename)
    ext = Path(filename).suffix.lower().lstrip(".")
    doc = Document(workspace_id=ps.WS, profile_id=profile.id, filename=filename,
                   mime=MIME.get(ext), storage_path=str(path), sha256=sha,
                   size_bytes=len(data), kind=kind[:30] or "resume")
    db.add(doc)
    db.flush()
    run = run_parse(db, profile, doc, use_llm=use_llm, parsed=parsed)
    audit(db, "document.upload", subject_type="document", subject_id=doc.id,
          detail={"kind": doc.kind, "size": doc.size_bytes, "sha256": sha256_hex(data)[:12]})
    return doc, run


_ = utcnow
