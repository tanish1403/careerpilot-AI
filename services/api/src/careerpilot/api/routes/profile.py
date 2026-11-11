"""Profile + typed item CRUD (contract: Lane B)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...db.models import User
from ...db.session import get_db
from ...documents import profile_service as ps
from ._laneb import to_http

router = APIRouter(tags=["profile"])


@router.get("/profiles/current")
def get_current(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return ps.profile_dict(db, ps.get_profile(db))


@router.put("/profiles/current")
def put_current(body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
                _: User = Depends(current_user)):
    p = ps.get_profile(db)
    try:
        ps.update_profile(db, p, body)
    except ps.ProfileError as e:
        raise to_http(e) from e
    return ps.profile_dict(db, p)


@router.get("/profiles/current/export")
def export(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return ps.export_profile(db, ps.get_profile(db))


@router.post("/profiles/import")
def import_(body: dict[str, Any] = Body(...), mode: str = Query("merge"),
            db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = ps.get_profile(db)
    try:
        res = ps.import_profile(db, p, body, mode, actor=user.username)
    except ps.ProfileError as e:
        raise to_http(e) from e
    return {**res, "profile": ps.profile_dict(db, p)}


def _register(path: str, category: str) -> None:
    @router.get(f"/{path}", name=f"list_{path}")
    def list_(status: str | None = None, limit: int = Query(50, ge=1, le=500),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db),
              _: User = Depends(current_user)):
        rows, total = ps.list_items(db, ps.get_profile(db), category, status=status,
                                    limit=limit, offset=offset)
        return {"items": [ps.item_dict(r, category) for r in rows], "total": total}

    @router.post(f"/{path}", status_code=201, name=f"create_{path}")
    def create(body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
               user: User = Depends(current_user)):
        try:
            row = ps.create_item(db, ps.get_profile(db), category, body, user.username)
        except ps.ProfileError as e:
            raise to_http(e) from e
        return ps.item_dict(row, category)

    @router.get(f"/{path}/{{item_id}}", name=f"get_{path}")
    def get(item_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
        try:
            return ps.item_dict(ps.get_item(db, category, item_id), category)
        except ps.ProfileError as e:
            raise to_http(e) from e

    def _update(item_id: str, body: dict[str, Any], db: Session, user: User):
        try:
            row = ps.update_item(db, ps.get_profile(db), category, item_id, body,
                                 user.username)
        except ps.ProfileError as e:
            raise to_http(e) from e
        return ps.item_dict(row, category)

    @router.patch(f"/{path}/{{item_id}}", name=f"patch_{path}")
    def patch(item_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
              user: User = Depends(current_user)):
        return _update(item_id, body, db, user)

    @router.put(f"/{path}/{{item_id}}", name=f"put_{path}")
    def put(item_id: str, body: dict[str, Any] = Body(...), db: Session = Depends(get_db),
            user: User = Depends(current_user)):
        return _update(item_id, body, db, user)

    @router.delete(f"/{path}/{{item_id}}", status_code=204, name=f"delete_{path}")
    def delete(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
        try:
            ps.delete_item(db, ps.get_profile(db), category, item_id, user.username)
        except ps.ProfileError as e:
            raise to_http(e) from e


for _path, _cat in ps.ROUTE_CATEGORY.items():
    _register(_path, _cat)

_ = HTTPException
