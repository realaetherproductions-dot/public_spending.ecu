from decimal import Decimal

from sqlalchemy.orm import Session

from models.procurement_rule import ProcurementRule
from pipelines.normalize_data import normalize_name


def normalize_procedure_type(value: str | None) -> str:
    return normalize_name(value).replace(" ", "_") if value else ""


def threshold_for_contract(
    db: Session,
    year: int | None,
    procedure_type: str | None,
) -> tuple[Decimal, ProcurementRule] | None:
    """Resolve an active, sourced threshold for an exact year/procedure.

    A wildcard procedure rule (``*``) is allowed, but there is deliberately no
    global numeric fallback: missing legal configuration must suppress the
    threshold-based flag instead of producing a potentially false allegation.
    """
    if year is None:
        return None
    normalized = normalize_procedure_type(procedure_type)
    candidates = [normalized, "*"] if normalized else ["*"]
    rule = (
        db.query(ProcurementRule)
        .filter(
            ProcurementRule.year == year,
            ProcurementRule.procedure_type.in_(candidates),
            ProcurementRule.active.is_(True),
        )
        .order_by(ProcurementRule.procedure_type.desc())
        .first()
    )
    if rule is None:
        return None
    return Decimal(rule.threshold), rule


def serialize_rule(rule: ProcurementRule) -> dict:
    return {
        "id": rule.id,
        "year": rule.year,
        "procedure_type": rule.procedure_type,
        "threshold": float(rule.threshold),
        "operator": rule.operator,
        "currency": rule.currency,
        "legal_reference": rule.legal_reference,
        "source_url": rule.source_url,
        "active": rule.active,
    }


def amount_is_within_rule(amount: Decimal, threshold: Decimal, operator: str) -> bool:
    if operator == "lte":
        return amount <= threshold
    return amount < threshold
