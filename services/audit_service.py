import json

from sqlalchemy.orm import Session

from models.audit_event import AuditEvent


def record_audit(
    db: Session,
    *,
    action: str,
    actor: str,
    target_type: str,
    target_id: str | int | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        actor=actor,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=json.dumps(details, ensure_ascii=False, sort_keys=True) if details else None,
    )
    db.add(event)
    return event
