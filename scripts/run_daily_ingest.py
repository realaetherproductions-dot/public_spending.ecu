import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from collectors.sercop_client import SercopClient
from models.ingestion_run import IngestionRun
from pipelines.ingest_contracts import ingest_contract_records


def main() -> None:
    init_db()
    client = SercopClient()

    params = {"institution": "INSTITUCION_PILOTO"}

    with SessionLocal() as db:
        run = IngestionRun(
            source_name="sercop",
            parameters=json.dumps(params, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        try:
            records = client.fetch_contracts_for_institution("INSTITUCION_PILOTO")

            inserted = ingest_contract_records(
                db, records, source_name="sercop", is_demo=False, ingestion_run_id=run_id,
            )

            run.status = "completed"
            run.records_fetched = len(records)
            run.records_new = inserted
            run.finished_at = datetime.utcnow()
            db.commit()

            print(f"[Run #{run_id}] Inserted {inserted} contract records")

        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            db.commit()
            print(f"[Run #{run_id}] FAILED: {exc}")
            raise


if __name__ == "__main__":
    main()
