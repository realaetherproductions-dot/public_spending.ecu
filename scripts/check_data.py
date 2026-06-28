"""Check what data is in the database — demo vs real."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func

from app.database import SessionLocal, init_db
from models.contract import Contract


def main() -> None:
    init_db()
    with SessionLocal() as db:
        total = db.query(Contract).count()
        demo = db.query(Contract).filter(Contract.is_demo.is_(True)).count()
        real = db.query(Contract).filter(Contract.is_demo.is_(False)).count()
        print(f"Total: {total}  |  Demo: {demo}  |  Real (SERCOP): {real}")
        print()

        print("Por data_origin:")
        for origin, count in db.query(Contract.data_origin, func.count()).group_by(Contract.data_origin).all():
            print(f"  {origin}: {count}")
        print()

        print("Primeros 5 contratos:")
        for c in db.query(Contract).order_by(Contract.id).limit(5).all():
            inst = c.institution.name if c.institution else "?"
            sup = c.supplier.name if c.supplier else "?"
            print(f"  [{c.id}] {c.external_id} | origin={c.data_origin} | demo={c.is_demo}")
            print(f"        {c.title[:80]}")
            print(f"        inst={inst} | sup={sup} | ${c.amount or 0}")
            print(f"        url={c.source_url}")
            print()

        print("Ultimos 5 contratos:")
        for c in db.query(Contract).order_by(Contract.id.desc()).limit(5).all():
            inst = c.institution.name if c.institution else "?"
            sup = c.supplier.name if c.supplier else "?"
            print(f"  [{c.id}] {c.external_id} | origin={c.data_origin} | demo={c.is_demo}")
            print(f"        {c.title[:80]}")
            print(f"        inst={inst} | sup={sup} | ${c.amount or 0}")
            print(f"        url={c.source_url}")
            print()


if __name__ == "__main__":
    main()
