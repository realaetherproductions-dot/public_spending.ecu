"""Export a human-review queue for the first 100 health-sector alerts."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import or_

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from models.anomaly import Anomaly
from models.contract import Contract
from models.institution import Institution


FIELDS = [
    "anomaly_id", "anomaly_type", "severity", "reason", "contract_id",
    "external_id", "institution", "supplier", "amount", "award_date",
    "procedure_type", "source_url", "decision", "reviewer",
    "review_evidence_url", "editorial_note",
]


def export_queue(output: Path, limit: int = 100) -> int:
    init_db()
    output.parent.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        rows = (
            db.query(Anomaly, Contract, Institution)
            .join(Contract, Anomaly.contract_id == Contract.id)
            .join(Institution, Contract.institution_id == Institution.id)
            .filter(
                Contract.is_demo.is_(False),
                Anomaly.status.in_(["open", "under_review"]),
                or_(
                    Institution.name.ilike("%HOSPITAL%"),
                    Institution.name.ilike("%SALUD%"),
                    Institution.name.ilike("%IESS%"),
                ),
            )
            .order_by(
                Anomaly.severity.desc(), Anomaly.anomaly_type, Anomaly.id,
            )
            .limit(limit)
            .all()
        )
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for anomaly, contract, institution in rows:
                writer.writerow({
                    "anomaly_id": anomaly.id,
                    "anomaly_type": anomaly.anomaly_type,
                    "severity": anomaly.severity,
                    "reason": anomaly.reason,
                    "contract_id": contract.id,
                    "external_id": contract.external_id,
                    "institution": institution.name,
                    "supplier": contract.supplier.name if contract.supplier else "",
                    "amount": contract.amount,
                    "award_date": contract.award_date,
                    "procedure_type": contract.procedure_type,
                    "source_url": contract.source_url,
                    "decision": "",
                    "reviewer": "",
                    "review_evidence_url": "",
                    "editorial_note": "",
                })
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/review/health_alerts_first_100.csv"),
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    count = export_queue(args.output, args.limit)
    print(f"Exported {count} alerts to {args.output}")


if __name__ == "__main__":
    main()
