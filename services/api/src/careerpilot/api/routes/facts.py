"""ProfileFact review endpoints: list, confirm, reject, edit."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import User
from ...db.session import get_db
from ...documents import profile_service as ps
from ._laneb import to_http

router = APIRouter(tags=["facts"])


@router.get("/facts")
def list_facts(status: str | None = None, category: str | None = None,
               document_id: str | None = None, limit: int = Query(50, ge=1, le=1000),
               offset: int = Query(0, ge=0), db: Session = Depends(get_db),
               _: User = Depends(current_user)):
    rows, total = ps.list_facts(db, ps.get_profile(db), status=status, category=category,
                                document_id=document_id, limit=limit, offset=offset)
    return {"items": [ps.fact_dict(f) for f in rows], "total": total}


@router.post("/facts/confirm-bulk")
def confirm_bulk(body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    p = ps.get_profile(db)
    done, failed = [], []
    for fid in body.get("ids", []):
        try:
            ps.confirm_fact(db, p, ps.get_fact(db, fid), user.username)
            done.append(fid)
        except ps.ProfileError as e:
            failed.append({"id": fid, "detail": e.detail})
    return {"confirmed": done, "failed": failed}


@router.get("/facts/{fact_id}")
def get_fact(fact_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    try:
        return ps.fact_dict(ps.get_fact(db, fact_id))
    except ps.ProfileError as e:
        raise to_http(e) from e


@router.post("/facts/{fact_id}/confirm")
def confirm(fact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        f = ps.confirm_fact(db, ps.get_profile(db), ps.get_fact(db, fact_id), user.username)
    except ps.ProfileError as e:
        raise to_http(e) from e
    return ps.fact_dict(f)


@router.post("/facts/{fact_id}/reject")
def reject(fact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        f = ps.reject_fact(db, ps.get_profile(db), ps.get_fact(db, fact_id), user.username)
    except ps.ProfileError as e:
        raise to_http(e) from e
    return ps.fact_dict(f)


@router.patch("/facts/{fact_id}")
def patch(fact_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
          user: User = Depends(current_user)):
    value = body.get("value")
    if not isinstance(value, dict):
        raise to_http(ps.ProfileError(422, "body must contain 'value' object"))
    try:
        f = ps.edit_fact(db, ps.get_profile(db), ps.get_fact(db, fact_id), value,
                         confirm=body.get("confirm") is True, actor=user.username)
    except ps.ProfileError as e:
        raise to_http(e) from e
    return ps.fact_dict(f)
