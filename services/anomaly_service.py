from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.anomaly import Anomaly
from models.anomaly_review import AnomalyReview
from services.audit_service import record_audit
from pipelines.detect_anomalies import detect_contract_anomalies


TERMINAL_REVIEW_STATUSES = {"confirmed", "discarded", "indeterminate"}
VALID_REVIEW_STATUSES = {"open", "under_review", *TERMINAL_REVIEW_STATUSES}


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
    reviewer: str | None = None,
    evidence_url: str | None = None,
) -> dict | None:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        return None

    if status == "dismissed":
        status = "discarded"
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {status}")
    if status in TERMINAL_REVIEW_STATUSES:
        if not reviewer or not reviewer.strip():
            raise ValueError("Terminal reviews require a reviewer")
        if not editorial_note or not editorial_note.strip():
            raise ValueError("Terminal reviews require an editorial note")

    anomaly.status = status
    if editorial_note is not None:
        anomaly.editorial_note = editorial_note
    if reviewer:
        now = datetime.now(timezone.utc)
        anomaly.reviewed_by = reviewer.strip()
        anomaly.reviewed_at = now
        anomaly.review_evidence_url = evidence_url
        db.add(AnomalyReview(
            anomaly_id=anomaly.id,
            status=status,
            reviewer=reviewer.strip(),
            evidence_url=evidence_url,
            note=editorial_note or "Cambio de estado editorial",
            reviewed_at=now,
        ))
        record_audit(
            db,
            action="anomaly.reviewed",
            actor=reviewer.strip(),
            target_type="anomaly",
            target_id=anomaly.id,
            details={"status": status, "evidence_url": evidence_url},
        )
    db.commit()
    db.refresh(anomaly)
    return _serialize_anomaly(anomaly)


def review_metrics(db: Session, target: int = 100) -> dict:
    rows = (
        db.query(Anomaly.anomaly_type, Anomaly.status, func.count(Anomaly.id))
        .group_by(Anomaly.anomaly_type, Anomaly.status)
        .all()
    )
    by_type: dict[str, dict[str, int | float | None]] = {}
    for anomaly_type, status, count in rows:
        item = by_type.setdefault(anomaly_type, {
            "confirmed": 0,
            "discarded": 0,
            "indeterminate": 0,
            "reviewed": 0,
            "precision": None,
        })
        if status in TERMINAL_REVIEW_STATUSES:
            item[status] = int(count)
            item["reviewed"] = int(item["reviewed"]) + int(count)

    totals = {"confirmed": 0, "discarded": 0, "indeterminate": 0, "reviewed": 0}
    for item in by_type.values():
        denominator = int(item["confirmed"]) + int(item["discarded"])
        item["precision"] = (
            round(int(item["confirmed"]) / denominator, 4) if denominator else None
        )
        for key in totals:
            totals[key] += int(item[key])

    denominator = totals["confirmed"] + totals["discarded"]
    return {
        **totals,
        "target": target,
        "remaining": max(target - totals["reviewed"], 0),
        "target_met": totals["reviewed"] >= target,
        "precision": round(totals["confirmed"] / denominator, 4) if denominator else None,
        "precision_definition": "confirmed / (confirmed + discarded); indeterminate excluded",
        "by_type": by_type,
    }


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
        "reviewed_by": anomaly.reviewed_by,
        "reviewed_at": anomaly.reviewed_at.isoformat() if anomaly.reviewed_at else None,
        "review_evidence_url": anomaly.review_evidence_url,
        "detected_at": anomaly.detected_at.isoformat() if anomaly.detected_at else None,
    }
    if include_details:
        data["details"] = anomaly.details
    return data
