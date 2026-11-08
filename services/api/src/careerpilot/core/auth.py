"""Single-user local auth: PBKDF2 password hash + HMAC-signed expiring bearer token."""
import base64, hashlib, hmac, json, os, time

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.session import get_db
from .config import get_settings
from .secrets import _key


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        s, _ = stored.split("$")
        return hmac.compare_digest(hash_password(pw, base64.b64decode(s)), stored)
    except Exception:
        return False


def make_token(username: str) -> str:
    exp = int(time.time()) + get_settings().session_ttl_hours * 3600
    body = base64.urlsafe_b64encode(json.dumps({"u": username, "exp": exp}).encode()).decode()
    sig = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(tok: str) -> str | None:
    try:
        body, sig = tok.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(body))
        return data["u"] if data["exp"] > time.time() else None
    except Exception:
        return None


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    """Dependency for every mutating (and data-reading) endpoint."""
    if get_settings().auth_disabled_for_tests:
        u = db.query(User).first()
        if not u:
            u = User(username="test", password_hash="x")
            db.add(u); db.flush()
        return u
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    name = read_token(authorization[7:])
    user = db.query(User).filter_by(username=name).first() if name else None
    if not user:
        raise HTTPException(401, "Invalid or expired session")
    return user
