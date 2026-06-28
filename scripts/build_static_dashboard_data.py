from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIRS = [ROOT / "data" / "raw" / "sercop_ocds", ROOT / "data" / "raw" / "demo"]
DB_FILE = ROOT / "data" / "processed" / "monitor.db"
OUT_FILE = ROOT / "frontend" / "dashboard" / "data.json"


def _parse_amount(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10]


def _get_id(name: str, registry: dict[str, int]) -> int:
    key = name.strip() or "No identificado"
    if key not in registry:
        registry[key] = len(registry) + 1
    return registry[key]


def _sqlite_rows(query: str) -> list[sqlite3.Row]:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    try:
        return list(con.execute(query))
    finally:
        con.close()


def _build_from_db() -> dict | None:
    if not DB_FILE.exists():
        return None

    contracts = [
        {
            "id": row["id"],
            "external_id": row["external_id"],
            "title": row["title"],
            "institution": row["institution"],
            "institution_id": row["institution_id"],
            "supplier": row["supplier"],
            "supplier_id": row["supplier_id"],
            "amount": _parse_amount(row["amount"]),
            "currency": row["currency"] or "USD",
            "award_date": _parse_date(row["award_date"]),
            "source_url": row["source_url"],
            "data_origin": row["data_origin"],
            "is_demo": bool(row["is_demo"]),
            "procedure_type": row["procedure_type"],
        }
        for row in _sqlite_rows(
            """
            select
              c.id, c.external_id, c.title, c.procedure_type, c.amount, c.currency,
              c.award_date, c.source_url, c.data_origin, c.is_demo,
              c.institution_id, i.name as institution,
              c.supplier_id, s.name as supplier
            from contracts c
            left join institutions i on i.id = c.institution_id
            left join suppliers s on s.id = c.supplier_id
            order by c.award_date desc, c.id desc
            """
        )
    ]

    anomalies = [
        {
            "id": row["id"],
            "contract_id": row["contract_id"],
            "anomaly_type": row["anomaly_type"],
            "severity": row["severity"],
            "score": row["score"],
            "reason": row["reason"],
            "details": row["details"],
            "status": row["status"],
            "editorial_note": row["editorial_note"],
            "detected_at": _parse_date(row["detected_at"]),
        }
        for row in _sqlite_rows(
            """
            select
              id, contract_id, anomaly_type, severity, score, reason, details,
              status, editorial_note, detected_at
            from anomalies
            order by id desc
            """
        )
    ]

    return _build_payload(contracts, anomalies, source="sqlite")


def _build_from_raw() -> dict:
    institutions: dict[str, int] = {}
    suppliers: dict[str, int] = {}
    contracts: list[dict] = []

    for raw_dir in RAW_DIRS:
        if not raw_dir.exists():
            continue
        for path in sorted(raw_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            institution = str(raw.get("institution") or "Institucion no identificada")
            supplier = str(raw.get("supplier") or "Proveedor no identificado")
            institution_id = _get_id(institution, institutions)
            supplier_id = _get_id(supplier, suppliers)
            contract_id = len(contracts) + 1

            contracts.append(
                {
                    "id": contract_id,
                    "external_id": raw.get("external_id") or path.stem,
                    "title": raw.get("title") or raw.get("external_id") or path.stem,
                    "institution": institution,
                    "institution_id": institution_id,
                    "supplier": supplier,
                    "supplier_id": supplier_id,
                    "amount": _parse_amount(raw.get("amount")),
                    "currency": "USD",
                    "award_date": _parse_date(raw.get("award_date")),
                    "source_url": raw.get("source_url"),
                    "data_origin": raw.get("data_origin") or "raw_json",
                    "is_demo": bool(raw.get("is_demo", False)),
                    "procedure_type": raw.get("procedure_type"),
                }
            )

    return _build_payload(contracts, [], source="raw_json")


def _build_payload(contracts: list[dict], anomalies: list[dict], source: str) -> dict:
    public_contracts = [c for c in contracts if not c["is_demo"]]
    total_amount = sum(c["amount"] or 0 for c in public_contracts)
    open_anomalies = [a for a in anomalies if a.get("status") == "open"]

    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": source,
        "stats": {
            "total_contracts": len(public_contracts),
            "total_institutions": len({c["institution_id"] for c in public_contracts}),
            "total_suppliers": len({c["supplier_id"] for c in public_contracts}),
            "open_anomalies": len(open_anomalies),
            "total_anomalies": len(anomalies),
            "total_amount": total_amount,
        },
        "contracts": sorted(
            contracts,
            key=lambda c: (c["award_date"] or "", c["id"]),
            reverse=True,
        ),
        "anomalies": anomalies,
    }


def main() -> None:
    payload = _build_from_db() or _build_from_raw()
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUT_FILE} from {payload['source']} with "
        f"{len(payload['contracts'])} contracts and {len(payload['anomalies'])} anomalies"
    )


if __name__ == "__main__":
    main()
