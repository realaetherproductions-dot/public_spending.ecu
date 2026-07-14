"""Isolated compliance tests for identity, rules, review, audit, and history."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base
from collectors.sercop_client import SercopClient
from models.anomaly import Anomaly
from models.anomaly_review import AnomalyReview
from models.audit_event import AuditEvent
from models.contract import Contract
from models.contract_event import ContractEvent
from models.correction_request import CorrectionRequest
from models.ingestion_run import IngestionRun
from models.institution import Institution
from models.procurement_rule import ProcurementRule
from models.raw_record import RawRecord
from models.supplier import Supplier
from pipelines.detect_anomalies import detect_contract_anomalies
from pipelines.ingest_contracts import ingest_contract_records
from services.anomaly_service import review_metrics, update_anomaly_status
from services.procurement_rule_service import normalize_procedure_type

_ = (
    Anomaly, AnomalyReview, AuditEvent, Contract, ContractEvent,
    CorrectionRequest, IngestionRun, Institution, ProcurementRule,
    RawRecord, Supplier,
)


def main() -> None:
    detail = {
        "compiledRelease": {
            "awards": [{
                "date": "2025-03-10",
                "value": {"amount": 3000, "currency": "USD"},
                "suppliers": [{
                    "name": "Proveedor Salud S.A.",
                    "identifier": {"scheme": "EC-RUC", "id": "179-001-234-5001"},
                }],
            }],
            "buyer": {"name": "Hospital Piloto"},
            "tender": {"procurementMethodDetails": "Infima Cuantia"},
        }
    }
    extracted = SercopClient._extract_award_details(detail)
    assert extracted["supplier_tax_id"] == "179-001-234-5001"

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with tempfile.TemporaryDirectory() as temp_dir:
        previous = Path.cwd()
        os.chdir(temp_dir)
        try:
            with Session() as db:
                run = IngestionRun(source_name="compliance", parameters="{}")
                db.add(run)
                db.commit()
                rule = ProcurementRule(
                    year=2025,
                    procedure_type=normalize_procedure_type("Infima Cuantia"),
                    threshold=7105.88,
                    legal_reference="Regla de prueba aislada",
                    source_url="https://example.org/official-rule",
                )
                db.add(rule)
                db.commit()

                base = {
                    "title": "Insumos de salud",
                    "institution": "Hospital Piloto",
                    "supplier_tax_id": "179-001-234-5001",
                    "amount": "3000.00",
                    "procedure_type": "Infima Cuantia",
                    "award_date": "2025-03-10",
                    "source_url": "https://example.org/source",
                }
                records = [
                    {**base, "external_id": "H-001", "supplier": "Proveedor Salud S.A."},
                    {**base, "external_id": "H-002", "supplier": "PROVEEDOR SALUD SA"},
                    {**base, "external_id": "H-003", "supplier": "Proveedor Salud"},
                ]
                assert ingest_contract_records(
                    db, records, "compliance", ingestion_run_id=run.id,
                ) == 3
                assert db.query(Supplier).count() == 1
                supplier = db.query(Supplier).one()
                assert supplier.tax_id == "1790012345001"

                created = detect_contract_anomalies(db)
                split_flags = [item for item in created if item.anomaly_type == "fraccionamiento"]
                assert len(split_flags) == 3
                details = json.loads(split_flags[0].details)
                assert details["procurement_rule_id"] == rule.id
                assert details["year"] == 2025

                reviewed = update_anomaly_status(
                    db,
                    split_flags[0].id,
                    "confirmed",
                    "Contratos y regla oficial revisados en la fuente.",
                    reviewer="compliance-reviewer",
                    evidence_url="https://example.org/review-evidence",
                )
                assert reviewed and reviewed["status"] == "confirmed"
                metrics = review_metrics(db)
                assert metrics["reviewed"] == 1
                assert metrics["precision"] == 1.0
                assert db.query(AnomalyReview).count() == 1
                assert db.query(AuditEvent).count() == 1

                changed = {**records[0], "amount": "3500.00"}
                ingest_contract_records(
                    db, [changed], "compliance", ingestion_run_id=run.id,
                )
                events = db.query(ContractEvent).filter(
                    ContractEvent.event_type == "field_changed",
                    ContractEvent.field_name == "amount",
                ).all()
                assert len(events) == 1
                assert events[0].old_value == "3000.00"
                assert events[0].new_value == "3500.00"
        finally:
            os.chdir(previous)

    print("PASS: identity, sourced thresholds, editorial review, audit, and history")


if __name__ == "__main__":
    main()
