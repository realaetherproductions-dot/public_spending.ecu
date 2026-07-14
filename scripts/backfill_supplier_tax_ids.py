"""Recover supplier identifiers from OCDS details already stored locally."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from collectors.sercop_client import SercopClient
from models.contract import Contract
from models.ingestion_run import IngestionRun
from models.institution import Institution
from models.raw_record import RawRecord
from models.supplier import Supplier
from pipelines.normalize_data import normalize_tax_id
from pipelines.ingest_contracts import ingest_contract_records


def backfill(apply: bool = False) -> dict:
    init_db()
    stats = {
        "raw_records_scanned": 0,
        "details_found": 0,
        "identifiers_found": 0,
        "suppliers_updated": 0,
        "contracts_relinked": 0,
        "conflicts": 0,
    }
    with SessionLocal() as db:
        rows = db.query(RawRecord).filter(RawRecord.contract_id.is_not(None)).all()
        for raw in rows:
            stats["raw_records_scanned"] += 1
            try:
                payload = json.loads(raw.payload)
            except (TypeError, json.JSONDecodeError):
                continue
            detail = payload.get("raw_detail")
            if not isinstance(detail, dict):
                continue
            stats["details_found"] += 1
            extracted = SercopClient._extract_award_details(detail)
            tax_id = normalize_tax_id(extracted.get("supplier_tax_id"))
            if not tax_id:
                continue
            stats["identifiers_found"] += 1
            contract = db.get(Contract, raw.contract_id)
            if contract is None or contract.supplier is None:
                continue
            supplier = contract.supplier
            canonical = db.query(Supplier).filter(Supplier.tax_id == tax_id).first()
            if canonical and canonical.id != supplier.id:
                contract.supplier = canonical
                stats["contracts_relinked"] += 1
            elif supplier.tax_id in (None, ""):
                supplier.tax_id = tax_id
                stats["suppliers_updated"] += 1
            elif supplier.tax_id != tax_id:
                stats["conflicts"] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    stats["mode"] = "apply" if apply else "dry-run"
    return stats


def fetch_missing_details(limit: int, health_only: bool, delay: float) -> dict:
    """Fetch missing OCDS details and re-ingest them as traceable raw records."""
    from sqlalchemy import or_

    init_db()
    client = SercopClient(request_delay_seconds=delay)
    stats = {"selected": 0, "fetched": 0, "with_identifier": 0, "failed": 0}
    with SessionLocal() as db:
        query = (
            db.query(Contract)
            .join(Institution)
            .join(Supplier)
            .filter(Contract.is_demo.is_(False), Supplier.tax_id.is_(None))
        )
        if health_only:
            query = query.filter(or_(
                Institution.name.ilike("%HOSPITAL%"),
                Institution.name.ilike("%SALUD%"),
                Institution.name.ilike("%IESS%"),
            ))
        contracts = query.order_by(Contract.id).limit(limit).all()
        stats["selected"] = len(contracts)
        run = IngestionRun(
            source_name="sercop_ocds_detail_backfill",
            parameters=json.dumps({"limit": limit, "health_only": health_only}),
        )
        db.add(run)
        db.commit()
        records = []
        for contract in contracts:
            try:
                detail = client.fetch_record_detail(contract.external_id)
                extracted = client._extract_award_details(detail)
                record = {
                    "external_id": contract.external_id,
                    "data_origin": "sercop_ocds",
                    "is_demo": False,
                    "title": contract.title,
                    "institution": extracted.get("institution") or contract.institution.name,
                    "supplier": extracted.get("supplier") or contract.supplier.name,
                    "supplier_tax_id": extracted.get("supplier_tax_id"),
                    "amount": extracted.get("amount") or (
                        str(contract.amount) if contract.amount is not None else None
                    ),
                    "currency": extracted.get("currency") or contract.currency,
                    "procedure_type": extracted.get("procedure_type") or contract.procedure_type,
                    "award_date": extracted.get("award_date") or (
                        contract.award_date.isoformat() if contract.award_date else None
                    ),
                    "source_url": contract.source_url,
                    "raw_detail": detail,
                }
                records.append(record)
                stats["fetched"] += 1
                if normalize_tax_id(record["supplier_tax_id"]):
                    stats["with_identifier"] += 1
            except Exception:
                stats["failed"] += 1
            if delay:
                time.sleep(delay)
        if records:
            ingest_contract_records(
                db,
                records,
                source_name="sercop_ocds",
                ingestion_run_id=run.id,
            )
        run.status = "completed" if stats["failed"] == 0 else "partial"
        run.records_fetched = stats["fetched"]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--health-only", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.fetch_missing:
        result = fetch_missing_details(args.limit, args.health_only, args.delay)
    else:
        result = backfill(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
