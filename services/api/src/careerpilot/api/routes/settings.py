"""Key/value app settings (JSON values). Secret-looking keys are rejected, never stored."""
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.audit import audit
from ...core.auth import current_user
from ...core.redaction import SENSITIVE_KEYS
from ...db.models import Setting
from ...db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_user)])
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


class SettingBody(BaseModel):
    value: Any = None


@router.get("")
def get_settings_map(db: Session = Depends(get_db)):
    return {r.key: r.value for r in db.query(Setting).order_by(Setting.key).all()}


@router.put("/{key}")
def put_setting(key: str, body: SettingBody, db: Session = Depends(get_db)):
    if not _KEY.match(key):
        raise HTTPException(422, "Invalid setting key")
    if SENSITIVE_KEYS.search(key):
        raise HTTPException(422, "Secrets must not be stored as settings; use the provider API")
    row = db.get(Setting, key)
    if row:
        row.value = body.value
    else:
        db.add(Setting(key=key, value=body.value))
    db.flush()
    audit(db, "settings.update", subject_type="setting", detail={"key": key})
    return {"key": key, "value": body.value}
