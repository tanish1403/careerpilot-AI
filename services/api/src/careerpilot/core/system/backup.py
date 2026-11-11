"""Backup / restore / export / wipe. Secrets are never exported; backups exclude the key file."""
import io
import json
import re
import shutil
import sqlite3
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from ...db.base import Base, utcnow
from ...db.session import reset_engine
from ..config import get_settings

BACKUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$")
DB_MEMBER = "db/careerpilot.db"
MANIFEST = "manifest.json"
FORMAT = "careerpilot-backup-v1"
FILE_DIRS = ("uploads", "artifacts")

# Tables never exported; columns never exported.
EXCLUDED_TABLES = {"secrets"}
EXCLUDED_COLUMNS = {"password_hash", "ciphertext"}
_SECRET_KEY = re.compile(
    r"^(api[_-]?key|secret|client_secret|password|passwd|authorization|cookie|set-cookie|"
    r"bearer|(access|refresh|auth|session|id)[_-]?token|token|ciphertext)$", re.I)


class BackupError(Exception):
    pass


def sqlite_path() -> Path:
    url = make_url(get_settings().db_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        raise BackupError("Backup requires a SQLite database")
    return Path(url.database)


def _stamp() -> str:
    return utcnow().strftime("%Y%m%d-%H%M%S-%f")


def safe_backup_path(filename: str) -> Path:
    if not BACKUP_RE.match(filename or ""):
        raise BackupError("Invalid backup filename")
    base = get_settings().backups_dir.resolve()
    p = (base / filename).resolve()
    if p.parent != base:
        raise BackupError("Invalid backup filename")
    return p


def _snapshot_db(dest: Path) -> None:
    """Consistent copy of the live DB using SQLite's online backup API."""
    src = sqlite3.connect(str(sqlite_path()))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(prefix: str = "careerpilot-backup") -> dict[str, Any]:
    s = get_settings()
    s.backups_dir.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}-{_stamp()}.zip"
    target = s.backups_dir / name
    tmp_db = s.backups_dir / f".snapshot-{_stamp()}.db"
    try:
        _snapshot_db(tmp_db)
        files: list[str] = []
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, DB_MEMBER)
            for d in FILE_DIRS:
                root = s.data_dir / d
                if not root.exists():
                    continue
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        arc = f"files/{d}/{p.relative_to(root).as_posix()}"
                        z.write(p, arc)
                        files.append(arc)
            z.writestr(MANIFEST, json.dumps({"format": FORMAT, "created_at": utcnow().isoformat(),
                                             "files": len(files), "db": DB_MEMBER}))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        tmp_db.unlink(missing_ok=True)
    return {"filename": name, "size_bytes": target.stat().st_size}


def list_backups() -> list[dict[str, Any]]:
    out = []
    for p in sorted(get_settings().backups_dir.glob("*.zip"), reverse=True):
        st = p.stat()
        out.append({"filename": p.name, "size_bytes": st.st_size,
                    "created_at": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat()})
    return out


def validate_backup(path: Path) -> zipfile.ZipFile:
    """Open and validate a backup zip; raises BackupError. Caller closes the ZipFile."""
    if not path.is_file():
        raise BackupError("Backup not found")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise BackupError("Not a valid zip file") from e
    try:
        names = z.namelist()
        for n in names:
            parts = Path(n).parts
            if n.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise BackupError("Unsafe path in backup")
        if MANIFEST not in names or DB_MEMBER not in names:
            raise BackupError("Not a CareerPilot backup (manifest or database missing)")
        try:
            man = json.loads(z.read(MANIFEST))
        except ValueError as e:
            raise BackupError("Corrupt manifest") from e
        if man.get("format") != FORMAT:
            raise BackupError("Unsupported backup format")
        if z.testzip() is not None:
            raise BackupError("Backup archive is corrupt")
        return z
    except BaseException:
        z.close()
        raise


def restore_backup(filename: str) -> dict[str, Any]:
    """Validate, take a pre-restore backup, then replace DB and uploads/artifacts."""
    s = get_settings()
    path = safe_backup_path(filename)
    z = validate_backup(path)
    try:
        tmp = s.backups_dir / f".restore-{_stamp()}.db"
        try:
            tmp.write_bytes(z.read(DB_MEMBER))
            chk = sqlite3.connect(str(tmp))
            try:
                ok = chk.execute("PRAGMA integrity_check").fetchone()
                tables = {r[0] for r in chk.execute(
                    "select name from sqlite_master where type='table'")}
            except sqlite3.DatabaseError as e:
                raise BackupError("Backup database is corrupt") from e
            finally:
                chk.close()
            if not ok or ok[0] != "ok":
                raise BackupError("Backup database failed integrity check")
            if "users" not in tables:
                raise BackupError("Backup database has no CareerPilot schema")

            pre = create_backup(prefix="pre-restore")
            reset_engine()  # release pooled connections before overwriting
            src = sqlite3.connect(str(tmp))
            dst = sqlite3.connect(str(sqlite_path()))
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
        finally:
            tmp.unlink(missing_ok=True)

        restored = 0
        members = [n for n in z.namelist()
                   if n.startswith("files/") and not n.endswith("/")]
        for d in FILE_DIRS:
            root = s.data_dir / d
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True, exist_ok=True)
        for n in members:
            rel = Path(n).relative_to("files")
            if rel.parts[0] not in FILE_DIRS:
                continue
            dest = (s.data_dir / rel).resolve()
            if (s.data_dir / rel.parts[0]).resolve() not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as fsrc, open(dest, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            restored += 1
    finally:
        z.close()
    return {"restored": filename, "files_restored": restored,
            "pre_restore_backup": pre["filename"]}


# ---- export / wipe ------------------------------------------------------------------
def _clean_json(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: ("[EXCLUDED]" if _SECRET_KEY.match(str(k)) else _clean_json(x))
                for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean_json(x) for x in v]
    return v


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return None
    return v


def export_zip_bytes(db: Session) -> bytes:
    buf = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table in Base.metadata.sorted_tables:
            if table.name in EXCLUDED_TABLES:
                continue
            cols = [c for c in table.columns if c.name not in EXCLUDED_COLUMNS]
            rows = db.execute(select(*cols)).mappings().all()
            data = [{k: _clean_json(_jsonable(v)) for k, v in r.items()} for r in rows]
            counts[table.name] = len(data)
            z.writestr(f"{table.name}.json", json.dumps(data, default=str, indent=1))
        z.writestr("manifest.json", json.dumps({
            "format": "careerpilot-export-v1", "created_at": utcnow().isoformat(),
            "tables": counts,
            "note": "Secrets, API keys and password hashes are excluded."}, indent=1))
    return buf.getvalue()


def delete_all_data(db: Session) -> dict[str, int]:
    """Remove all user data and uploaded/generated files. Keeps the login account
    and the backups directory."""
    removed: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "users":
            continue
        res = db.execute(delete(table))
        removed[table.name] = res.rowcount or 0
    db.flush()
    s = get_settings()
    for d in FILE_DIRS:
        root = s.data_dir / d
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
    return removed


def db_size() -> int:
    try:
        return sqlite_path().stat().st_size
    except Exception:  # noqa: BLE001
        return 0


__all__ = ["BackupError", "create_backup", "list_backups", "restore_backup", "export_zip_bytes",
           "delete_all_data", "safe_backup_path", "db_size"]
