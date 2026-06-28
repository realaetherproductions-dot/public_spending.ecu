from sqlalchemy.orm import Session

from models.anomaly import Anomaly
from pipelines.detect_anomalies import detect_contract_anomalies


def list_anomalies(
    db: Session,
    status: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    query = db.query(Anomaly)
    if status:
        query = query.filter(Anomaly.status == status)
    if severity:
        query = query.filter(Anomaly.severity == severity)

    return [_serialize_anomaly(a) for a in query.order_by(Anomaly.id.desc()).all()]


def run_detection(db: Session, detection_run_id: int | None = None) -> int:
    created = detect_contract_anomalies(db, detection_run_id=detection_run_id)
    return len(created)


def update_anomaly_status(
    db: Session,
    anomaly_id: int,
    status: str,
    editorial_note: str | None = None,
) -> dict | None:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        return None

    anomaly.status = status
    if editorial_note is not None:
        anomaly.editorial_note = editorial_note
    db.commit()
    db.refresh(anomaly)
    return _serialize_anomaly(anomaly)


def get_anomaly(db: Session, anomaly_id: int) -> dict | None:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        return None
    return _serialize_anomaly(anomaly, include_details=True)


def _serialize_anomaly(anomaly: Anomaly, include_details: bool = False) -> dict:
    data = {
        "id": anomaly.id,
        "contract_id": anomaly.contract_id,
        "anomaly_type": anomaly.anomaly_type,
        "severity": anomaly.severity,
        "score": anomaly.score,
        "reason": anomaly.reason,
        "status": anomaly.status,
        "editorial_note": anomaly.editorial_note,
        "detected_at": anomaly.detected_at.isoformat() if anomaly.detected_at else None,
    }
    if include_details:
        data["details"] = anomaly.details
    return data
