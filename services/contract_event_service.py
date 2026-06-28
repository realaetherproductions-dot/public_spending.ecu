from sqlalchemy.orm import Session

from models.contract_event import ContractEvent


def list_contract_events(db: Session, contract_id: int) -> list[dict]:
    events = (
        db.query(ContractEvent)
        .filter(ContractEvent.contract_id == contract_id)
        .order_by(ContractEvent.detected_at.asc())
        .all()
    )
    return [_serialize_event(e) for e in events]


def _serialize_event(event: ContractEvent) -> dict:
    return {
        "id": event.id,
        "contract_id": event.contract_id,
        "event_type": event.event_type,
        "field_name": event.field_name,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "raw_record_id": event.raw_record_id,
        "detected_at": event.detected_at.isoformat() if event.detected_at else None,
    }
