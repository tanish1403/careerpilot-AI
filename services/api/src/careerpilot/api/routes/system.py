"""Diagnostics, logs, backup/restore, export and data wipe."""
import importlib.util
import platform
import shutil
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user
from ...core.config import get_settings
from ...core.system import backup as bk
from ...core.system.bootstrap import current_revision, register
from ...db.models import AuditEvent
from ...db.session import get_db

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(current_user)])

register()  # append the safe schema-bootstrap startup hook to STARTUP_HOOKS


class RestoreBody(BaseModel):
    filename: str


class WipeBody(BaseModel):
    confirm: str = ""


def _scheduler_running() -> bool:
    try:
        from ...scheduler import service  # type: ignore[attr-defined]
        fn = getattr(service, "is_running", None)
        return bool(fn()) if callable(fn) else False
    except Exception:  # noqa: BLE001
        return False


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db)) -> dict[str, Any]:
    s = get_settings()
    try:
        db.execute(select(1))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    try:
        free = shutil.disk_usage(s.data_dir).free
    except OSError:
        free = 0
    tools = {
        "xelatex": shutil.which("xelatex") is not None,
        "tesseract": shutil.which("tesseract") is not None,
        "playwright": importlib.util.find_spec("playwright") is not None,
        "ollama": shutil.which("ollama") is not None,
    }
    return {"version": "0.1.0", "python": platform.python_version(),
            "platform": sys.platform,
            "db": {"ok": ok, "size_bytes": bk.db_size(), "migration": current_revision()},
            "disk_free_bytes": free, "tools": tools,
            "scheduler": {"running": _scheduler_running()}}


def _events(db: Session, limit: int, prefix: str | None = None) -> dict[str, Any]:
    stmt = select(AuditEvent).where(AuditEvent.deleted_at.is_(None))
    if prefix:
        stmt = stmt.where(AuditEvent.action.like(f"{prefix}%"))
    rows = db.execute(stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                      .limit(limit)).scalars().all()
    return {"items": [{"id": r.id, "action": r.action, "actor": r.actor,
                       "subject_type": r.subject_type, "subject_id": r.subject_id,
                       "detail": r.detail, "created_at": r.created_at.isoformat()}
                      for r in rows]}


@router.get("/logs")
def logs(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    return _events(db, limit)


@router.get("/events")
def events(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    return _events(db, limit)


@router.post("/backup")
def make_backup(db: Session = Depends(get_db)):
    try:
        res = bk.create_backup()
    except bk.BackupError as e:
        raise HTTPException(400, str(e)) from e
    audit(db, "system.backup", detail={"filename": res["filename"]})
    return res


@router.get("/backups")
def backups():
    return {"items": bk.list_backups()}


@router.get("/backups/{filename}")
def download_backup(filename: str):
    try:
        p = bk.safe_backup_path(filename)
    except bk.BackupError as e:
        raise HTTPException(400, str(e)) from e
    if not p.is_file():
        raise HTTPException(404, "Backup not found")
    return FileResponse(p, media_type="application/zip", filename=p.name)


@router.post("/restore")
def restore(body: RestoreBody):
    try:
        res = bk.restore_backup(body.filename)
    except bk.BackupError as e:
        raise HTTPException(422 if "not found" not in str(e).lower() else 404, str(e)) from e
    # audit goes to the restored DB through a fresh session
    from ...db.session import session_scope
    with session_scope() as db2:
        audit(db2, "system.restore", detail={"filename": body.filename})
    return res


@router.get("/export")
def export(db: Session = Depends(get_db)):
    data = bk.export_zip_bytes(db)
    audit(db, "system.export")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="careerpilot-export.zip"'})


@router.delete("/data")
def wipe(body: WipeBody, db: Session = Depends(get_db)):
    if body.confirm != "DELETE":
        raise HTTPException(422, 'Send {"confirm": "DELETE"} to erase all data')
    removed = bk.delete_all_data(db)
    audit(db, "system.data_deleted")
    return {"deleted": True, "tables": removed}
