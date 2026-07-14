"""Smoke test for Phase 1 migration: ingestion_runs + raw_records + last_raw_record_id."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_DB = Path("data/processed/test_phase1.db")
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///./{TEST_DB.as_posix()}"

from app.database import SessionLocal, init_db
from models.ingestion_run import IngestionRun
from models.raw_record import RawRecord
from models.contract import Contract
from pipelines.ingest_contracts import ingest_contract_records

RECORDS = [
    {
        "external_id": "TST1",
        "title": "Compra de suministros",
        "institution": "GAD Quito",
        "supplier": "Prov A",
        "amount": "5000.00",
        "source_url": "https://example.org/TST1",
    },
    {
        "external_id": "TST2",
        "title": "Consultoria tecnica",
        "institution": "GAD Quito",
        "supplier": "Prov B",
        "amount": "15000.00",
        "source_url": "https://example.org/TST2",
    },
]

MODIFIED = [
    {
        "external_id": "TST1",
        "title": "Compra de suministros",
        "institution": "GAD Quito",
        "supplier": "Prov A",
        "amount": "7500.00",
        "source_url": "https://example.org/TST1",
    },
]


def main() -> None:
    init_db()
    errors = 0

    with SessionLocal() as db:
        # --- Test 1: First ingest creates raw_records and contracts ---
        run = IngestionRun(source_name="test", parameters=json.dumps({"type": "e2e"}))
        db.add(run)
        db.commit()
        db.refresh(run)

        inserted = ingest_contract_records(db, RECORDS, source_name="test", ingestion_run_id=run.id)
        run.status = "completed"
        run.records_fetched = len(RECORDS)
        run.records_new = inserted
        run.finished_at = datetime.utcnow()
        db.commit()

        assert inserted == 2, f"Expected 2 new contracts, got {inserted}"
        print("PASS: 1st ingest created 2 contracts")

        raw_count = db.query(RawRecord).count()
        assert raw_count == 2, f"Expected 2 raw_records, got {raw_count}"
        print("PASS: 2 raw_records created")

        c1 = db.query(Contract).filter(Contract.external_id == "TST1").first()
        assert c1 is not None
        assert c1.last_raw_record_id is not None, "Contract should have last_raw_record_id"
        print(f"PASS: Contract TST1 linked to raw_record #{c1.last_raw_record_id}")

        rr1 = db.get(RawRecord, c1.last_raw_record_id)
        assert rr1.contract_id == c1.id, "RawRecord should back-link to contract"
        assert rr1.ingestion_run_id == run.id, "RawRecord should link to ingestion_run"
        print("PASS: RawRecord correctly linked to contract and ingestion_run")

        # --- Test 2: Duplicate ingest skips (same hash) ---
        run2 = IngestionRun(source_name="test", parameters="{}")
        db.add(run2)
        db.commit()
        db.refresh(run2)

        inserted2 = ingest_contract_records(db, RECORDS, source_name="test", ingestion_run_id=run2.id)
        assert inserted2 == 0, f"Expected 0 new on duplicate, got {inserted2}"

        raw_count2 = db.query(RawRecord).count()
        assert raw_count2 == 2, f"Expected still 2 raw_records, got {raw_count2}"
        print("PASS: Duplicate ingest correctly skipped (same payload hash)")

        # --- Test 3: Modified payload creates new raw_record, updates contract ---
        original_raw_id = c1.last_raw_record_id

        run3 = IngestionRun(source_name="test", parameters="{}")
        db.add(run3)
        db.commit()
        db.refresh(run3)

        inserted3 = ingest_contract_records(db, MODIFIED, source_name="test", ingestion_run_id=run3.id)
        assert inserted3 == 0, f"Expected 0 new (contract exists), got {inserted3}"

        raw_count3 = db.query(RawRecord).count()
        assert raw_count3 == 3, f"Expected 3 raw_records (new hash), got {raw_count3}"

        db.refresh(c1)
        assert c1.last_raw_record_id != original_raw_id, (
            f"Contract should point to new raw_record after payload change "
            f"(was {original_raw_id}, now {c1.last_raw_record_id})"
        )
        print("PASS: Modified payload created new raw_record and updated contract link")

        # --- Test 4: IngestionRun stats ---
        r = db.get(IngestionRun, run.id)
        assert r.status == "completed"
        assert r.records_fetched == 2
        assert r.records_new == 2
        assert r.finished_at is not None
        print("PASS: IngestionRun stats correct")

    print("\n=== ALL PHASE 1 TESTS PASSED ===")


if __name__ == "__main__":
    main()
