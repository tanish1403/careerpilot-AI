"""Wiring for routes: gateway factory with injectable transport (tests) and mock mode."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.models import Setting

transport = None      # tests set an httpx.MockTransport here
sleep = None          # tests may set an instant async sleep


def mock_mode(db: Session) -> bool:
    row = db.get(Setting, "agent_mock_mode")
    return bool(row and row.value in (True, "true", "1"))


def make_gateway(db: Session):
    from .gateway import Gateway
    return Gateway(db, transport=transport, sleep=sleep)
