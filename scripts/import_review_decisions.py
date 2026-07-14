"""Validate and import completed human review decisions from CSV."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from services.anomaly_service import TERMINAL_REVIEW_STATUSES, update_anomaly_status


def import_decisions(path: Path, apply: bool = False) -> dict:
    init_db()
    stats = {"rows": 0, "ready": 0, "imported": 0, "errors": []}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    stats["rows"] = len(rows)
    with SessionLocal() as db:
        for line_number, row in enumerate(rows, start=2):
            decision = (row.get("decision") or "").strip().lower()
            if not decision:
                continue
            reviewer = (row.get("reviewer") or "").strip()
            note = (row.get("editorial_note") or "").strip()
            evidence = (row.get("review_evidence_url") or "").strip() or None
            if decision not in TERMINAL_REVIEW_STATUSES:
                stats["errors"].append(f"line {line_number}: invalid decision {decision!r}")
                continue
            if not reviewer or not note:
                stats["errors"].append(f"line {line_number}: reviewer and note are required")
                continue
            try:
                anomaly_id = int(row["anomaly_id"])
            except (KeyError, TypeError, ValueError):
                stats["errors"].append(f"line {line_number}: invalid anomaly_id")
                continue
            stats["ready"] += 1
            if apply:
                result = update_anomaly_status(
                    db,
                    anomaly_id,
                    decision,
                    note,
                    reviewer=reviewer,
                    evidence_url=evidence,
                )
                if result is None:
                    stats["errors"].append(f"line {line_number}: anomaly not found")
                else:
                    stats["imported"] += 1
        if not apply:
            db.rollback()
    stats["mode"] = "apply" if apply else "dry-run"
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = import_decisions(args.input, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
