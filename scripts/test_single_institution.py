import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from models.ingestion_run import IngestionRun
from pipelines.ingest_contracts import ingest_contract_records


SAMPLE_RECORDS = [
    {
        "external_id": "MVP-001",
        "data_origin": "demo",
        "is_demo": True,
        "title": "Adquisicion de equipos informaticos",
        "institution": "Municipio Piloto",
        "supplier": "Proveedor Demo S.A.",
        "supplier_tax_id": "1790000000001",
        "procedure_type": "Subasta inversa electronica",
        "amount": "12000.00",
        "award_date": "2026-01-15",
        "source_url": "https://example.org/contratos/MVP-001",
    },
    {
        "external_id": "MVP-002",
        "data_origin": "demo",
        "is_demo": True,
        "title": "Servicio de consultoria especializada",
        "institution": "Municipio Piloto",
        "supplier": "Consultora Demo Cia. Ltda.",
        "procedure_type": "Contratacion directa",
        "amount": "55000.00",
        "award_date": "2026-02-20",
        "source_url": None,
    },
]


def main() -> None:
    init_db()
    with SessionLocal() as db:
        run = IngestionRun(
            source_name="demo",
            parameters=json.dumps({"type": "sample_records"}, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        inserted = ingest_contract_records(
            db, SAMPLE_RECORDS, source_name="demo", is_demo=True, ingestion_run_id=run.id,
        )

        run.status = "completed"
        run.records_fetched = len(SAMPLE_RECORDS)
        run.records_new = inserted
        run.finished_at = datetime.utcnow()
        db.commit()

    print(f"Inserted {inserted} sample records")


if __name__ == "__main__":
    main()
