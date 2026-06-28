from sqlalchemy.orm import Session

from models.contract import Contract
from models.supplier import Supplier


def supplier_summary(db: Session, supplier_id: int) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        return {"supplier_id": supplier_id, "found": False}

    contracts = db.query(Contract).filter(Contract.supplier_id == supplier_id).all()
    total = sum((contract.amount or 0 for contract in contracts), start=0)
    return {
        "supplier_id": supplier.id,
        "found": True,
        "name": supplier.name,
        "tax_id": supplier.tax_id,
        "contract_count": len(contracts),
        "total_awarded": float(total),
    }

