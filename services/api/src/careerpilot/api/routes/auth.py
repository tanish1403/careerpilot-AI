"""First-run setup + login. Single local user; tokens are HMAC-signed and expiring."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user, hash_password, make_token, verify_password
from ...db.models import User
from ...db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

_FAILS: dict[str, deque] = defaultdict(deque)
_WINDOW_S, _MAX_FAILS = 300, 10
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


def _throttled(name: str) -> bool:
    q = _FAILS[name]
    now = time.time()
    while q and q[0] < now - _WINDOW_S:
        q.popleft()
    return len(q) >= _MAX_FAILS


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"setup_required": db.query(User).count() == 0}


@router.post("/setup")
def setup(body: Credentials, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(409, "Setup already completed")
    username = body.username.strip()
    if not username:
        raise HTTPException(422, "Username required")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    db.add(User(username=username, password_hash=hash_password(body.password), role="owner"))
    db.flush()
    audit(db, "auth.setup", actor=username)
    return {"token": make_token(username)}


@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    name = body.username.strip()
    if _throttled(name):
        raise HTTPException(429, "Too many failed attempts; try again later")
    user = db.query(User).filter_by(username=name).first()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        _FAILS[name].append(time.time())
        audit(db, "auth.login_failed", actor=name[:100])
        db.commit()  # keep the audit row even though we raise
        raise HTTPException(401, "Invalid username or password")
    _FAILS.pop(name, None)
    audit(db, "auth.login", actor=user.username)
    return {"token": make_token(user.username)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"username": user.username, "setup_required": False}
