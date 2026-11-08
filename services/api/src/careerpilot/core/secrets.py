"""Encrypted secret store (Fernet). Key lives in data_dir, never in the DB or API."""
import os
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from ..db.models import Secret
from .config import get_settings


def _key() -> bytes:
    p = get_settings().data_dir / get_settings().secret_key_file
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p.read_bytes()


def set_secret(db: Session, name: str, value: str) -> None:
    ct = Fernet(_key()).encrypt(value.encode()).decode()
    row = db.get(Secret, name)
    if row:
        row.ciphertext = ct
    else:
        db.add(Secret(name=name, ciphertext=ct))
    db.flush()


def get_secret(db: Session, name: str | None) -> str | None:
    if not name:
        return None
    row = db.get(Secret, name)
    return Fernet(_key()).decrypt(row.ciphertext.encode()).decode() if row else None


def has_secret(db: Session, name: str | None) -> bool:
    return bool(name and db.get(Secret, name))


def delete_secret(db: Session, name: str) -> None:
    row = db.get(Secret, name)
    if row:
        db.delete(row)
        db.flush()
