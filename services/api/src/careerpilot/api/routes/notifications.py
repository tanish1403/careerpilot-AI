from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.auth import current_user
from ...core.redaction import redact
from ...core.system.runs import iso
from ...db.models import Notification
from ...db.session import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"],
                   dependencies=[Depends(current_user)])


def _n(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "read": n.read,
            "payload": redact(n.payload or {}), "created_at": iso(n.created_at)}


@router.get("")
def list_notifications(unread: bool = False, limit: int = Query(50, ge=1, le=500),
                       offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    cond = [Notification.deleted_at.is_(None)]
    if unread:
        cond.append(Notification.read.is_(False))
    total = db.execute(select(func.count()).select_from(Notification).where(*cond)).scalar_one()
    unread_n = db.execute(select(func.count()).select_from(Notification).where(
        Notification.deleted_at.is_(None), Notification.read.is_(False))).scalar_one()
    rows = db.execute(select(Notification).where(*cond).order_by(Notification.created_at.desc())
                      .limit(limit).offset(offset)).scalars().all()
    return {"items": [_n(r) for r in rows], "total": total, "unread": unread_n}


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.deleted_at is not None:
        raise HTTPException(404, "Notification not found")
    n.read = True
    db.flush()
    return _n(n)
