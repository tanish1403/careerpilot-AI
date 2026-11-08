from sqlalchemy.orm import Session

from ..db.models import AuditEvent
from .redaction import redact


def audit(db: Session, action: str, *, actor: str | None = None, subject_type: str | None = None,
          subject_id: str | None = None, detail: dict | None = None) -> AuditEvent:
    ev = AuditEvent(action=action, actor=actor, subject_type=subject_type, subject_id=subject_id,
                    detail=redact(detail or {}))
    db.add(ev)
    db.flush()
    return ev
