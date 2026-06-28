from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIRS = [ROOT / "data" / "raw" / "sercop_ocds", ROOT / "data" / "raw" / "demo"]
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


def main() -> None:
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

    public_contracts = [c for c in contracts if not c["is_demo"]]
    total_amount = sum(c["amount"] or 0 for c in public_contracts)

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "stats": {
            "total_contracts": len(public_contracts),
            "total_institutions": len({c["institution_id"] for c in public_contracts}),
            "total_suppliers": len({c["supplier_id"] for c in public_contracts}),
            "open_anomalies": 0,
            "total_anomalies": 0,
            "total_amount": total_amount,
        },
        "contracts": sorted(
            contracts,
            key=lambda c: (c["award_date"] or "", c["id"]),
            reverse=True,
        ),
        "anomalies": [],
    }

    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_FILE} with {len(contracts)} contracts")


if __name__ == "__main__":
    main()
