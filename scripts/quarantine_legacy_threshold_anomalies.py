"""Quarantine threshold flags created before sourced procurement rules existed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from models.anomaly import Anomaly
from services.audit_service import record_audit


def quarantine(apply: bool) -> dict:
    init_db()
    with SessionLocal() as db:
        candidates = db.query(Anomaly).filter(
            Anomaly.anomaly_type.in_(["fraccionamiento", "monto_bajo_umbral"]),
            Anomaly.status.in_(["open", "under_review"]),
        ).all()
        legacy = []
        for anomaly in candidates:
            try:
                details = json.loads(anomaly.details or "{}")
            except json.JSONDecodeError:
                details = {}
            if not details.get("procurement_rule_id"):
                legacy.append(anomaly)
        if apply:
            for anomaly in legacy:
                anomaly.status = "superseded"
                anomaly.editorial_note = (
                    "Invalidada como alerta operativa: fue calculada antes del catálogo "
                    "de reglas SERCOP por año y procedimiento. Debe redetectarse."
                )
            record_audit(
                db,
                action="anomalies.legacy_threshold_quarantined",
                actor="compliance-migration",
                target_type="anomaly",
                details={"count": len(legacy)},
            )
            db.commit()
        else:
            db.rollback()
    return {"legacy_threshold_anomalies": len(legacy), "mode": "apply" if apply else "dry-run"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(quarantine(args.apply), indent=2))


if __name__ == "__main__":
    main()
