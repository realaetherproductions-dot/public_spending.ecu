import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from models.contract import Contract
from models.contract_event import ContractEvent
from models.institution import Institution
from models.raw_record import RawRecord
from models.supplier import Supplier
from pipelines.hashing import compute_payload_hash
from pipelines.normalize_data import normalize_name, parse_amount, parse_iso_date


@dataclass
class IngestStats:
    fetched: int = 0
    new: int = 0
    changed: int = 0
    skipped: int = 0


TRACKED_FIELDS = {
    "amount": lambda r: str(parse_amount(r.get("amount")) or ""),
    "supplier": lambda r: str(r.get("supplier") or ""),
    "institution": lambda r: str(r.get("institution") or ""),
    "title": lambda r: str(r.get("title") or r.get("description") or ""),
    "procedure_type": lambda r: str(r.get("procedure_type") or ""),
    "award_date": lambda r: str(parse_iso_date(r.get("award_date")) or ""),
    "source_url": lambda r: str(r.get("source_url") or ""),
}


def _detect_changes(
    contract: Contract,
    record: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Compare tracked fields and return list of (field_name, old_value, new_value)."""
    changes: list[tuple[str, str, str]] = []

    contract_values = {
        "amount": str(contract.amount or ""),
        "supplier": contract.supplier.name if contract.supplier else "",
        "institution": contract.institution.name if contract.institution else "",
        "title": contract.title or "",
        "procedure_type": contract.procedure_type or "",
        "award_date": str(contract.award_date or ""),
        "source_url": contract.source_url or "",
    }

    for field, extractor in TRACKED_FIELDS.items():
        old = contract_values.get(field, "")
        new = extractor(record)
        if old != new and new:
            changes.append((field, old, new))

    return changes


def ingest_contract_records(
    db: Session,
    records: list[dict[str, Any]],
    source_name: str,
    is_demo: bool = False,
    ingestion_run_id: int | None = None,
) -> int:
    raw_dir = Path("data/raw") / source_name
    raw_dir.mkdir(parents=True, exist_ok=True)

    stats = IngestStats()

    for record in records:
        external_id = str(record.get("external_id") or record.get("id") or "").strip()
        if not external_id:
            continue

        stats.fetched += 1
        payload_hash = compute_payload_hash(record)

        existing_raw = (
            db.query(RawRecord)
            .filter(
                RawRecord.source_name == source_name,
                RawRecord.source_id == external_id,
                RawRecord.payload_hash == payload_hash,
            )
            .first()
        )

        if existing_raw:
            stats.skipped += 1
            continue

        raw_record = RawRecord(
            ingestion_run_id=ingestion_run_id,
            source_name=source_name,
            source_id=external_id,
            source_url=record.get("source_url"),
            payload=json.dumps(record, ensure_ascii=False, indent=2),
            payload_hash=payload_hash,
        )
        db.add(raw_record)
        db.flush()

        safe_id = external_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        raw_path = raw_dir / f"{safe_id}.json"
        raw_path.write_text(raw_record.payload, encoding="utf-8")

        existing_contract = db.query(Contract).filter(Contract.external_id == external_id).first()

        if existing_contract:
            changes = _detect_changes(existing_contract, record)
            for field_name, old_value, new_value in changes:
                event = ContractEvent(
                    contract_id=existing_contract.id,
                    raw_record_id=raw_record.id,
                    event_type="field_changed",
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                )
                db.add(event)

            existing_contract.data_origin = str(record.get("data_origin") or source_name)
            existing_contract.is_demo = bool(record.get("is_demo", is_demo))
            existing_contract.last_raw_record_id = raw_record.id

            new_amount = parse_amount(record.get("amount"))
            if new_amount is not None:
                existing_contract.amount = new_amount
            new_supplier_name = record.get("supplier")
            if new_supplier_name and new_supplier_name != "Proveedor desconocido":
                existing_contract.supplier = _get_or_create_supplier(
                    db, new_supplier_name, record.get("supplier_tax_id"),
                )
            new_institution_name = record.get("institution")
            if new_institution_name and new_institution_name != "Institucion desconocida":
                existing_contract.institution = _get_or_create_institution(db, new_institution_name)
            if record.get("source_url"):
                existing_contract.source_url = record["source_url"]
            if record.get("procedure_type"):
                existing_contract.procedure_type = record["procedure_type"]
            new_date = parse_iso_date(record.get("award_date"))
            if new_date:
                existing_contract.award_date = new_date

            raw_record.contract_id = existing_contract.id
            stats.changed += 1
        else:
            institution_name = str(record.get("institution") or "Institucion desconocida")
            supplier_name = str(record.get("supplier") or "Proveedor desconocido")

            institution = _get_or_create_institution(db, institution_name)
            supplier = _get_or_create_supplier(db, supplier_name, record.get("supplier_tax_id"))

            contract = Contract(
                external_id=external_id,
                title=str(record.get("title") or record.get("description") or "Contrato sin titulo"),
                procedure_type=record.get("procedure_type"),
                amount=parse_amount(record.get("amount")),
                currency=str(record.get("currency") or "USD"),
                award_date=parse_iso_date(record.get("award_date")),
                source_url=record.get("source_url"),
                data_origin=str(record.get("data_origin") or source_name),
                is_demo=bool(record.get("is_demo", is_demo)),
                raw_payload_path=str(raw_path),
                last_raw_record_id=raw_record.id,
                institution=institution,
                supplier=supplier,
            )
            db.add(contract)
            db.flush()
            raw_record.contract_id = contract.id

            db.add(ContractEvent(
                contract_id=contract.id,
                raw_record_id=raw_record.id,
                event_type="created",
            ))

            stats.new += 1

    db.commit()
    return stats.new


def _get_or_create_institution(db: Session, name: str) -> Institution:
    normalized = normalize_name(name)
    institution = db.query(Institution).filter(Institution.normalized_name == normalized).first()
    if institution:
        return institution
    institution = Institution(name=name, normalized_name=normalized)
    db.add(institution)
    db.flush()
    return institution


def _get_or_create_supplier(db: Session, name: str, tax_id: str | None = None) -> Supplier:
    normalized = normalize_name(name)
    supplier = db.query(Supplier).filter(Supplier.normalized_name == normalized).first()
    if supplier:
        return supplier
    supplier = Supplier(name=name, normalized_name=normalized, tax_id=tax_id)
    db.add(supplier)
    db.flush()
    return supplier
