"""Smoke test for Phase 2: anomalies as a persistent table with editorial status."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_DB = Path("data/processed/test_phase2.db")
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///./{TEST_DB.as_posix()}"

from app.database import SessionLocal, init_db
from models.anomaly import Anomaly
from models.ingestion_run import IngestionRun
from models.raw_record import RawRecord
from models.contract import Contract
from pipelines.detect_anomalies import detect_contract_anomalies
from pipelines.ingest_contracts import ingest_contract_records
from services.anomaly_service import list_anomalies, run_detection, update_anomaly_status

RECORDS = [
    {
        "external_id": "ANO-001",
        "title": "Consultoria de alto monto",
        "institution": "Municipio Test",
        "supplier": "Proveedor Caro S.A.",
        "amount": "500000.00",
        "source_url": "https://example.org/ANO-001",
    },
    {
        "external_id": "ANO-002",
        "title": "Compra de suministros",
        "institution": "Municipio Test",
        "supplier": "Proveedor Normal A",
        "amount": "1000.00",
        "source_url": "https://example.org/ANO-002",
    },
    {
        "external_id": "ANO-003",
        "title": "Servicio sin fuente",
        "institution": "Municipio Test",
        "supplier": "Proveedor Opaco",
        "amount": "2000.00",
        "source_url": None,
    },
    {
        "external_id": "ANO-004",
        "title": "Mantenimiento vial",
        "institution": "Municipio Test",
        "supplier": "Proveedor Normal B",
        "amount": "3000.00",
        "source_url": "https://example.org/ANO-004",
    },
    {
        "external_id": "ANO-005",
        "title": "Limpieza de oficinas",
        "institution": "Municipio Test",
        "supplier": "Proveedor Normal C",
        "amount": "1500.00",
        "source_url": "https://example.org/ANO-005",
    },
    {
        "external_id": "ANO-006",
        "title": "Material de oficina",
        "institution": "Municipio Test",
        "supplier": "Proveedor Normal D",
        "amount": "800.00",
        "source_url": "https://example.org/ANO-006",
    },
    {
        "external_id": "ANO-007",
        "title": "Capacitacion personal",
        "institution": "Municipio Test",
        "supplier": "Proveedor Normal E",
        "amount": "2500.00",
        "source_url": "https://example.org/ANO-007",
    },
]


def main() -> None:
    init_db()

    with SessionLocal() as db:
        # Setup: ingest test contracts
        run = IngestionRun(source_name="test", parameters=json.dumps({"type": "phase2"}))
        db.add(run)
        db.commit()
        db.refresh(run)

        inserted = ingest_contract_records(db, RECORDS, source_name="test", ingestion_run_id=run.id)
        # avg = (500000+1000+2000+3000+1500+800+2500)/7 = ~72971 -> 500k is ~6.8x avg
        print(f"Setup: inserted {inserted} contracts")

        # --- Test 1: Detect anomalies and persist ---
        created = detect_contract_anomalies(db, detection_run_id=run.id)
        print(f"Anomalies created: {len(created)}")

        all_anomalies = db.query(Anomaly).all()
        assert len(all_anomalies) >= 2, f"Expected at least 2 anomalies, got {len(all_anomalies)}"

        types = {a.anomaly_type for a in all_anomalies}
        assert "high_amount" in types, "Should detect high_amount anomaly (500k vs avg ~167k)"
        assert "missing_traceability" in types, "Should detect missing_traceability anomaly"
        print("PASS: Anomalies detected and persisted (high_amount + missing_traceability)")

        # Verify anomalies have correct defaults
        for a in all_anomalies:
            assert a.status == "open", f"New anomaly should have status 'open', got '{a.status}'"
            assert a.editorial_note is None
        print("PASS: New anomalies default to status='open', editorial_note=None")

        # --- Test 2: Idempotent re-detection ---
        created2 = detect_contract_anomalies(db, detection_run_id=run.id)
        assert len(created2) == 0, f"Re-detection should create 0 new anomalies, got {len(created2)}"

        count_after = db.query(Anomaly).count()
        assert count_after == len(all_anomalies), "Re-detection should not duplicate anomalies"
        print("PASS: Re-detection is idempotent (no duplicates)")

        # --- Test 3: Update anomaly status ---
        anomaly_id = all_anomalies[0].id
        result = update_anomaly_status(
            db,
            anomaly_id,
            "discarded",
            "Falso positivo verificado manualmente",
            reviewer="test-reviewer",
            evidence_url="https://example.org/evidence",
        )
        assert result is not None
        assert result["status"] == "discarded"
        assert result["editorial_note"] == "Falso positivo verificado manualmente"
        print("PASS: Anomaly status updated to 'discarded' with editorial note")

        # --- Test 4: Filter anomalies by status ---
        open_anomalies = list_anomalies(db, status="open")
        discarded_anomalies = list_anomalies(db, status="discarded")
        assert len(discarded_anomalies) == 1
        assert len(open_anomalies) == len(all_anomalies) - 1
        print("PASS: Filtering anomalies by status works")

        # --- Test 5: Filter by severity ---
        high_anomalies = list_anomalies(db, severity="high")
        assert all(a["severity"] == "high" for a in high_anomalies)
        print(f"PASS: Filtering by severity works ({len(high_anomalies)} high severity)")

        # --- Test 6: list_anomalies returns correct shape ---
        all_serialized = list_anomalies(db)
        for a in all_serialized:
            assert "id" in a
            assert "contract_id" in a
            assert "anomaly_type" in a
            assert "severity" in a
            assert "status" in a
            assert "reason" in a
        print("PASS: Serialized anomalies have correct shape")

        # --- Test 7: run_detection via service ---
        count = run_detection(db)
        assert count == 0, "run_detection on already-detected data should return 0"
        print("PASS: run_detection service works (idempotent)")

        # --- Test 8: update nonexistent anomaly ---
        result_none = update_anomaly_status(
            db, 99999, "confirmed", "Evidencia suficiente",
            reviewer="test-reviewer",
        )
        assert result_none is None
        print("PASS: Updating nonexistent anomaly returns None")

    print("\n=== ALL PHASE 2 TESTS PASSED ===")


if __name__ == "__main__":
    main()
