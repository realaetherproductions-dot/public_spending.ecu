from datetime import date

from sqlalchemy.orm import Session

from models.contract import Contract
from models.institution import Institution
from models.supplier import Supplier


def search_contracts(
    db: Session,
    query: str | None = None,
    institution_name: str | None = None,
    data_origin: str | None = None,
    include_demo: bool = True,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    statement = db.query(Contract).join(Institution, isouter=True).join(Supplier, isouter=True)
    if query:
        like = f"%{query}%"
        statement = statement.filter(
            Contract.title.ilike(like)
            | Institution.name.ilike(like)
            | Supplier.name.ilike(like)
            | Contract.external_id.ilike(like)
        )
    if institution_name:
        statement = statement.filter(Institution.name.ilike(f"%{institution_name}%"))
    if data_origin:
        statement = statement.filter(Contract.data_origin == data_origin)
    if not include_demo:
        statement = statement.filter(Contract.is_demo.is_(False))
    if date_from:
        statement = statement.filter(Contract.award_date >= date_from)
    if date_to:
        statement = statement.filter(Contract.award_date <= date_to)

    return [_serialize_contract(contract) for contract in statement.order_by(Contract.award_date.desc().nullslast(), Contract.id.desc()).limit(200)]


def _serialize_contract(contract: Contract) -> dict:
    return {
        "id": contract.id,
        "external_id": contract.external_id,
        "title": contract.title,
        "institution": contract.institution.name if contract.institution else None,
        "institution_id": contract.institution_id,
        "supplier": contract.supplier.name if contract.supplier else None,
        "supplier_id": contract.supplier_id,
        "amount": float(contract.amount) if contract.amount is not None else None,
        "currency": contract.currency,
        "award_date": contract.award_date.isoformat() if contract.award_date else None,
        "source_url": contract.source_url,
        "data_origin": contract.data_origin,
        "is_demo": contract.is_demo,
    }
