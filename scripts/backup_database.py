"""Create and verify SQLite backups without interrupting the API."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def verify_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"Backup integrity check failed for {path}: {result}")


def create_backup(source: Path, output_dir: Path, retention: int) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"monitor-{stamp}.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
    verify_database(destination)

    backups = sorted(output_dir.glob("monitor-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for expired in backups[max(retention, 1):]:
        expired.unlink()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/processed/monitor.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/backups"))
    parser.add_argument("--retention", type=int, default=14)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        verify_database(args.verify)
        print(f"OK: {args.verify}")
        return
    destination = create_backup(args.database, args.output_dir, args.retention)
    print(f"Backup verified: {destination}")


if __name__ == "__main__":
    main()
