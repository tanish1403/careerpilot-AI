"""Lane E: supervised browser automation routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...applications import automation as auto
from ...applications.service import ApplicationError
from ...browser_automation.adapters import list_adapters
from ...browser_automation.allowlist import DEFAULT_ALLOWLIST, get_allowlist, set_allowlist
from ...core.audit import audit
from ...core.auth import current_user
from ...db.models import User
from ...db.session import get_db

router = APIRouter(prefix="/automation", tags=["automation"])


def _call(fn, *a, **kw):  # noqa: ANN001
    try:
        return fn(*a, **kw)
    except ApplicationError as e:
        raise HTTPException(e.status, e.detail) from None


class SessionBody(BaseModel):
    application_id: str
    headed: bool | None = None


@router.get("/allowlist")
def get_list(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"domains": get_allowlist(db), "default": list(DEFAULT_ALLOWLIST)}


@router.put("/allowlist")
def put_list(body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    domains = body.get("domains")
    if not isinstance(domains, list):
        raise HTTPException(422, "body must be {domains: [hostname, ...]}")
    try:
        clean = set_allowlist(db, [str(d) for d in domains])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    audit(db, "automation.allowlist.update", actor=user.username, subject_type="setting",
          detail={"count": len(clean)})
    return {"domains": clean, "default": list(DEFAULT_ALLOWLIST)}


@router.get("/adapters")
def adapters(_: User = Depends(current_user)):
    return list_adapters()


@router.post("/sessions", status_code=201)
def create_session(body: SessionBody, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    s = _call(auto.start_session, db, body.application_id, user.username, body.headed)
    return s.public()


@router.get("/sessions/{sid}")
def get_session(sid: str, _: User = Depends(current_user)):
    return _call(auto.get_session, sid).public()


@router.post("/sessions/{sid}/fill-preview")
def fill_preview(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _call(auto.preview, db, _call(auto.get_session, sid), user.username)


@router.post("/sessions/{sid}/autofill")
def autofill(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _call(auto.autofill, db, _call(auto.get_session, sid), user.username)


@router.post("/sessions/{sid}/stop")
def stop(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _call(auto.stop_session, db, _call(auto.get_session, sid), user.username)


@router.get("/sessions/{sid}/screenshot")
def screenshot(sid: str, _: User = Depends(current_user)):
    p = auto.screenshot_path(_call(auto.get_session, sid))
    if p is None:
        raise HTTPException(404, "No review screenshot yet")
    return FileResponse(str(p), media_type="image/png")


def _register_shutdown() -> None:
    try:  # close any live browsers when the app stops
        from ..app import SHUTDOWN_HOOKS
        from ...browser_automation.session import MANAGER
        SHUTDOWN_HOOKS.append(lambda _app: MANAGER.shutdown_all())
    except Exception:  # noqa: BLE001
        pass


_register_shutdown()
