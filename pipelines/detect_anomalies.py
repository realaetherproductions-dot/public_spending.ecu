import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.anomaly import Anomaly
from models.contract import Contract
from models.contract_event import ContractEvent


UMBRAL_CONTRATACION_DIRECTA = Decimal("7105.88")
MARGEN_BAJO_UMBRAL = Decimal("0.15")


def detect_contract_anomalies(
    db: Session,
    detection_run_id: int | None = None,
) -> list[Anomaly]:
    contracts = db.query(Contract).filter(Contract.is_demo.is_(False)).all()
    if not contracts:
        return []

    created: list[Anomaly] = []
    created += _detect_high_amount(db, contracts, detection_run_id)
    created += _detect_missing_traceability(db, contracts, detection_run_id)
    created += _detect_fraccionamiento(db, contracts, detection_run_id)
    created += _detect_proveedor_recurrente(db, contracts, detection_run_id)
    created += _detect_concentracion_institucional(db, contracts, detection_run_id)
    created += _detect_fechas_sospechosas(db, contracts, detection_run_id)
    created += _detect_monto_bajo_umbral(db, contracts, detection_run_id)
    created += _detect_escalamiento_monto(db, detection_run_id)

    db.commit()
    return created


def _detect_high_amount(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    amounts = [c.amount for c in contracts if c.amount is not None]
    if not amounts:
        return []
    average = sum(amounts, Decimal("0")) / len(amounts)
    created: list[Anomaly] = []
    for contract in contracts:
        if contract.amount is not None and average and contract.amount >= average * 3:
            ratio = float(contract.amount / average)
            a = _get_or_create_anomaly(
                db, contract.id, "high_amount", "medium", ratio,
                f"Monto {ratio:.1f}x mayor que el promedio (${float(average):,.2f})",
                json.dumps({"amount": float(contract.amount), "average": float(average), "ratio": ratio}),
                run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_missing_traceability(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    created: list[Anomaly] = []
    for contract in contracts:
        if contract.source_url is None:
            a = _get_or_create_anomaly(
                db, contract.id, "missing_traceability", "high", None,
                "Contrato sin URL de fuente verificable", None, run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_fraccionamiento(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    """Mismo proveedor + misma institucion con 3+ contratos cuya suma supera
    el umbral de licitacion pero cada uno esta por debajo."""
    groups: dict[tuple[int | None, int | None], list[Contract]] = defaultdict(list)
    for c in contracts:
        if c.supplier_id and c.institution_id and c.amount is not None:
            groups[(c.supplier_id, c.institution_id)].append(c)

    created: list[Anomaly] = []
    for (sup_id, inst_id), group in groups.items():
        below_threshold = [c for c in group if c.amount < UMBRAL_CONTRATACION_DIRECTA]
        if len(below_threshold) < 3:
            continue
        total = sum(c.amount for c in below_threshold)
        if total <= UMBRAL_CONTRATACION_DIRECTA:
            continue

        supplier_name = group[0].supplier.name if group[0].supplier else "?"
        inst_name = group[0].institution.name if group[0].institution else "?"
        score = float(len(below_threshold))

        for c in below_threshold:
            a = _get_or_create_anomaly(
                db, c.id, "fraccionamiento", "high", score,
                f"Posible fraccionamiento: {len(below_threshold)} contratos con {supplier_name} "
                f"en {inst_name} suman ${float(total):,.2f} (cada uno bajo umbral de ${float(UMBRAL_CONTRATACION_DIRECTA):,.2f})",
                json.dumps({
                    "supplier": supplier_name, "institution": inst_name,
                    "contract_count": len(below_threshold), "total": float(total),
                    "contract_ids": [c.id for c in below_threshold],
                }),
                run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_proveedor_recurrente(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    """Un proveedor que gana contratos en 5+ instituciones distintas."""
    supplier_institutions: dict[int, set[int]] = defaultdict(set)
    supplier_contracts: dict[int, list[Contract]] = defaultdict(list)
    for c in contracts:
        if c.supplier_id and c.institution_id:
            supplier_institutions[c.supplier_id].add(c.institution_id)
            supplier_contracts[c.supplier_id].append(c)

    created: list[Anomaly] = []
    for sup_id, inst_ids in supplier_institutions.items():
        if len(inst_ids) < 5:
            continue
        contracts_for_sup = supplier_contracts[sup_id]
        supplier_name = contracts_for_sup[0].supplier.name if contracts_for_sup[0].supplier else "?"
        total = sum(c.amount for c in contracts_for_sup if c.amount) or Decimal("0")
        score = float(len(inst_ids))

        for c in contracts_for_sup:
            a = _get_or_create_anomaly(
                db, c.id, "proveedor_recurrente", "medium", score,
                f"{supplier_name} tiene contratos en {len(inst_ids)} instituciones distintas "
                f"(total ${float(total):,.2f})",
                json.dumps({
                    "supplier": supplier_name,
                    "institution_count": len(inst_ids),
                    "contract_count": len(contracts_for_sup),
                    "total": float(total),
                }),
                run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_concentracion_institucional(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    """Una institucion asigna 40%+ de sus contratos al mismo proveedor
    (minimo 4 contratos en la institucion)."""
    inst_contracts: dict[int, list[Contract]] = defaultdict(list)
    for c in contracts:
        if c.institution_id and c.supplier_id:
            inst_contracts[c.institution_id].append(c)

    created: list[Anomaly] = []
    for inst_id, group in inst_contracts.items():
        if len(group) < 4:
            continue
        supplier_counts: dict[int, int] = defaultdict(int)
        for c in group:
            supplier_counts[c.supplier_id] += 1

        for sup_id, count in supplier_counts.items():
            ratio = count / len(group)
            if ratio < 0.4:
                continue

            affected = [c for c in group if c.supplier_id == sup_id]
            supplier_name = affected[0].supplier.name if affected[0].supplier else "?"
            inst_name = affected[0].institution.name if affected[0].institution else "?"
            total = sum(c.amount for c in affected if c.amount) or Decimal("0")

            for c in affected:
                a = _get_or_create_anomaly(
                    db, c.id, "concentracion_institucional", "high", ratio * 100,
                    f"{inst_name} asigna {ratio:.0%} de sus contratos ({count}/{len(group)}) "
                    f"a {supplier_name} (${float(total):,.2f})",
                    json.dumps({
                        "institution": inst_name, "supplier": supplier_name,
                        "supplier_contracts": count, "total_contracts": len(group),
                        "ratio": round(ratio, 3), "total_amount": float(total),
                    }),
                    run_id,
                )
                if a:
                    created.append(a)
    return created


def _detect_fechas_sospechosas(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    """Contratos adjudicados en los ultimos 5 dias del ano fiscal (dic 27-31)."""
    created: list[Anomaly] = []
    for c in contracts:
        if not c.award_date:
            continue
        if c.award_date.month == 12 and c.award_date.day >= 27:
            a = _get_or_create_anomaly(
                db, c.id, "fecha_sospechosa", "low", float(c.award_date.day),
                f"Adjudicado el {c.award_date.strftime('%d/%m/%Y')} — ultimos dias del ano fiscal",
                json.dumps({"date": str(c.award_date), "day_of_year": c.award_date.timetuple().tm_yday}),
                run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_monto_bajo_umbral(
    db: Session, contracts: list[Contract], run_id: int | None,
) -> list[Anomaly]:
    """Contratos con monto entre 85% y 100% del umbral de contratacion directa."""
    floor = UMBRAL_CONTRATACION_DIRECTA * (1 - MARGEN_BAJO_UMBRAL)
    created: list[Anomaly] = []
    for c in contracts:
        if c.amount is None:
            continue
        if floor <= c.amount < UMBRAL_CONTRATACION_DIRECTA:
            pct = float(c.amount / UMBRAL_CONTRATACION_DIRECTA) * 100
            a = _get_or_create_anomaly(
                db, c.id, "monto_bajo_umbral", "low", pct,
                f"Monto ${float(c.amount):,.2f} es {pct:.1f}% del umbral de contratacion directa "
                f"(${float(UMBRAL_CONTRATACION_DIRECTA):,.2f})",
                json.dumps({
                    "amount": float(c.amount),
                    "threshold": float(UMBRAL_CONTRATACION_DIRECTA),
                    "percentage": round(pct, 2),
                }),
                run_id,
            )
            if a:
                created.append(a)
    return created


def _detect_escalamiento_monto(
    db: Session, run_id: int | None,
) -> list[Anomaly]:
    """Contratos cuyo monto ha aumentado 2+ veces entre ingestas."""
    amount_changes = (
        db.query(
            ContractEvent.contract_id,
            func.count(ContractEvent.id).label("change_count"),
        )
        .filter(
            ContractEvent.event_type == "field_changed",
            ContractEvent.field_name == "amount",
        )
        .group_by(ContractEvent.contract_id)
        .having(func.count(ContractEvent.id) >= 2)
        .all()
    )

    created: list[Anomaly] = []
    for contract_id, change_count in amount_changes:
        events = (
            db.query(ContractEvent)
            .filter(
                ContractEvent.contract_id == contract_id,
                ContractEvent.event_type == "field_changed",
                ContractEvent.field_name == "amount",
            )
            .order_by(ContractEvent.detected_at)
            .all()
        )

        increases = [e for e in events if _is_amount_increase(e.old_value, e.new_value)]
        if len(increases) < 2:
            continue

        first_amount = _parse_event_amount(increases[0].old_value)
        last_amount = _parse_event_amount(increases[-1].new_value)
        if first_amount and last_amount and first_amount > 0:
            growth = float((last_amount - first_amount) / first_amount) * 100
        else:
            growth = 0.0

        contract = db.get(Contract, contract_id)
        a = _get_or_create_anomaly(
            db, contract_id, "escalamiento_monto", "critical", growth,
            f"Monto aumentado {len(increases)} veces "
            f"(crecimiento total: {growth:.1f}%)",
            json.dumps({
                "increase_count": len(increases),
                "total_changes": change_count,
                "growth_pct": round(growth, 2),
                "history": [
                    {"old": e.old_value, "new": e.new_value, "date": str(e.detected_at)}
                    for e in increases
                ],
            }),
            run_id,
        )
        if a:
            created.append(a)
    return created


def _is_amount_increase(old: str | None, new: str | None) -> bool:
    old_val = _parse_event_amount(old)
    new_val = _parse_event_amount(new)
    if old_val is None or new_val is None:
        return False
    return new_val > old_val


def _parse_event_amount(val: str | None) -> Decimal | None:
    if not val:
        return None
    try:
        return Decimal(val.replace(",", ""))
    except Exception:
        return None


def _get_or_create_anomaly(
    db: Session,
    contract_id: int,
    anomaly_type: str,
    severity: str,
    score: float | None,
    reason: str,
    details: str | None,
    detection_run_id: int | None,
) -> Anomaly | None:
    existing = (
        db.query(Anomaly)
        .filter(
            Anomaly.contract_id == contract_id,
            Anomaly.anomaly_type == anomaly_type,
        )
        .first()
    )
    if existing:
        existing.score = score
        existing.reason = reason
        existing.details = details
        return None

    anomaly = Anomaly(
        contract_id=contract_id,
        anomaly_type=anomaly_type,
        severity=severity,
        score=score,
        reason=reason,
        details=details,
        detection_run_id=detection_run_id,
    )
    db.add(anomaly)
    return anomaly
