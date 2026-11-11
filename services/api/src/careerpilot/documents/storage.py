"""Immutable, content-addressed storage for original uploads."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from ..core.config import get_settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip().strip(".") or "upload"
    return base[:200]


def store_original(data: bytes, filename: str) -> tuple[str, Path]:
    """Write <sha256><ext> under data/uploads, never overwriting. Returns (sha, path)."""
    sha = sha256_hex(data)
    ext = Path(safe_filename(filename)).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext or ""):
        ext = ""
    dest = get_settings().uploads_dir / f"{sha}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        try:
            dest.chmod(0o444)
        except OSError:  # pragma: no cover - Windows / odd FS
            pass
    return sha, dest
