"""Smoke test for Phase 3: contract_events — change history tracking."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_DB = Path("data/processed/test_phase3.db")
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///./{TEST_DB.as_posix()}"

from app.database import SessionLocal, init_db
from models.contract import Contract
from models.contract_event import ContractEvent
from models.ingestion_run import IngestionRun
from pipelines.ingest_contracts import ingest_contract_records
from services.contract_event_service import list_contract_events

INITIAL = [
    {
        "external_id": "EVT-001",
        "title": "Compra de insumos medicos",
        "institution": "Hospital General",
        "supplier": "Farmacia Nacional S.A.",
        "amount": "25000.00",
        "award_date": "2025-03-15",
        "source_url": "https://example.org/EVT-001",
    },
    {
        "external_id": "EVT-002",
        "title": "Servicio de limpieza",
        "institution": "Hospital General",
        "supplier": "Limpieza Total Cia.",
        "amount": "8000.00",
        "award_date": "2025-04-01",
        "source_url": "https://example.org/EVT-002",
    },
]

MODIFIED = [
    {
        "external_id": "EVT-001",
        "title": "Compra de insumos medicos",
        "institution": "Hospital General",
        "supplier": "Distribuidora Medica S.A.",
        "amount": "32000.00",
        "award_date": "2025-03-15",
        "source_url": "https://example.org/EVT-001",
    },
]

MODIFIED_AGAIN = [
    {
        "external_id": "EVT-001",
        "title": "Compra de insumos medicos - ampliacion",
        "institution": "Hospital General",
        "supplier": "Distribuidora Medica S.A.",
        "amount": "45000.00",
        "award_date": "2025-06-01",
        "source_url": "https://example.org/EVT-001",
    },
]


def main() -> None:
    init_db()

    with SessionLocal() as db:
        # --- Test 1: Initial ingest creates 'created' events ---
        run1 = IngestionRun(source_name="test", parameters="{}")
        db.add(run1)
        db.commit()
        db.refresh(run1)

        inserted = ingest_contract_records(db, INITIAL, source_name="test", ingestion_run_id=run1.id)
        assert inserted == 2

        created_events = db.query(ContractEvent).filter(ContractEvent.event_type == "created").all()
        assert len(created_events) == 2, f"Expected 2 'created' events, got {len(created_events)}"

        for ev in created_events:
            assert ev.field_name is None
            assert ev.old_value is None
            assert ev.new_value is None
            assert ev.raw_record_id is not None
        print("PASS: Initial ingest created 2 'created' events")

        # --- Test 2: Modified ingest creates field_changed events ---
        contract_before = db.query(Contract).filter(Contract.external_id == "EVT-001").first()
        contract_id = contract_before.id

        run2 = IngestionRun(source_name="test", parameters="{}")
        db.add(run2)
        db.commit()
        db.refresh(run2)

        ingest_contract_records(db, MODIFIED, source_name="test", ingestion_run_id=run2.id)

        change_events = (
            db.query(ContractEvent)
            .filter(ContractEvent.contract_id == contract_id, ContractEvent.event_type == "field_changed")
            .all()
        )

        changed_fields = {ev.field_name for ev in change_events}
        assert "amount" in changed_fields, f"Expected amount change, got {changed_fields}"
        assert "supplier" in changed_fields, f"Expected supplier change, got {changed_fields}"
        print(f"PASS: Detected field changes: {changed_fields}")

        amount_event = next(ev for ev in change_events if ev.field_name == "amount")
        assert amount_event.old_value == "25000.00"
        assert amount_event.new_value == "32000.00"
        print(f"PASS: Amount change recorded: {amount_event.old_value} -> {amount_event.new_value}")

        supplier_event = next(ev for ev in change_events if ev.field_name == "supplier")
        assert supplier_event.old_value == "Farmacia Nacional S.A."
        assert supplier_event.new_value == "Distribuidora Medica S.A."
        print(f"PASS: Supplier change recorded: {supplier_event.old_value} -> {supplier_event.new_value}")

        # Verify contract was actually updated
        db.refresh(contract_before)
        assert str(contract_before.amount) == "32000.00"
        assert contract_before.supplier.name == "Distribuidora Medica S.A."
        print("PASS: Contract fields actually updated in DB")

        # --- Test 3: Second modification adds more events ---
        run3 = IngestionRun(source_name="test", parameters="{}")
        db.add(run3)
        db.commit()
        db.refresh(run3)

        ingest_contract_records(db, MODIFIED_AGAIN, source_name="test", ingestion_run_id=run3.id)

        all_events = (
            db.query(ContractEvent)
            .filter(ContractEvent.contract_id == contract_id)
            .order_by(ContractEvent.detected_at.asc())
            .all()
        )

        event_types = [(ev.event_type, ev.field_name) for ev in all_events]
        print(f"Full event history for EVT-001: {event_types}")

        assert len(all_events) >= 4, f"Expected at least 4 events (1 created + 2 first change + changes), got {len(all_events)}"
        assert all_events[0].event_type == "created"
        print("PASS: Full chronological history maintained")

        # --- Test 4: Service returns correct data ---
        history = list_contract_events(db, contract_id)
        assert len(history) == len(all_events)
        assert all("event_type" in h for h in history)
        assert all("detected_at" in h for h in history)
        assert history[0]["event_type"] == "created"
        print("PASS: list_contract_events service works correctly")

        # --- Test 5: Unchanged contract (EVT-002) has only 'created' event ---
        evt002 = db.query(Contract).filter(Contract.external_id == "EVT-002").first()
        evt002_events = list_contract_events(db, evt002.id)
        assert len(evt002_events) == 1
        assert evt002_events[0]["event_type"] == "created"
        print("PASS: Unchanged contract only has 'created' event")

        # --- Test 6: Duplicate ingest creates no events ---
        event_count_before = db.query(ContractEvent).count()

        run4 = IngestionRun(source_name="test", parameters="{}")
        db.add(run4)
        db.commit()
        db.refresh(run4)
        ingest_contract_records(db, MODIFIED_AGAIN, source_name="test", ingestion_run_id=run4.id)

        event_count_after = db.query(ContractEvent).count()
        assert event_count_after == event_count_before, "Duplicate ingest should not create new events"
        print("PASS: Duplicate ingest (same hash) creates no events")

    print("\n=== ALL PHASE 3 TESTS PASSED ===")


if __name__ == "__main__":
    main()
