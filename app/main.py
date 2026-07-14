from datetime import date
from pathlib import Path
import threading

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, init_db
from services.anomaly_service import get_anomaly, list_anomalies, run_detection, update_anomaly_status
from services.contract_event_service import list_contract_events
from services.contract_service import search_contracts
from services.supplier_service import supplier_summary

settings = get_settings()
app = FastAPI(title=settings.app_name)

_ingest_lock = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dashboard"


def require_admin(x_admin_token: str | None = Header(default=None)) -> str:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Token administrativo requerido")
    return "admin"


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/contracts")
def contracts(
    q: str | None = Query(default=None),
    institution: str | None = Query(default=None),
    data_origin: str | None = Query(default=None),
    include_demo: bool = Query(default=True),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return search_contracts(
        db=db,
        query=q,
        institution_name=institution,
        data_origin=data_origin,
        include_demo=include_demo,
        date_from=date_from,
        date_to=date_to,
    )


@app.get("/suppliers/search")
def suppliers_search(q: str = Query(default=""), db: Session = Depends(get_db)) -> list[dict]:
    from models.supplier import Supplier
    query = db.query(Supplier)
    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))
    return [{"id": s.id, "name": s.name, "tax_id": s.tax_id}
            for s in query.order_by(Supplier.name).limit(25).all()]


@app.get("/suppliers/{supplier_id}/summary")
def supplier(supplier_id: int, db: Session = Depends(get_db)) -> dict:
    return supplier_summary(db=db, supplier_id=supplier_id)


@app.get("/suppliers/{supplier_id}/profile")
def supplier_profile(supplier_id: int, db: Session = Depends(get_db)) -> dict:
    from collections import defaultdict
    from models.anomaly import Anomaly
    from models.contract import Contract
    from models.supplier import Supplier
    from services.contract_service import _serialize_contract

    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    contracts = (
        db.query(Contract)
        .filter(Contract.supplier_id == supplier_id, Contract.is_demo.is_(False))
        .order_by(Contract.award_date.desc())
        .all()
    )

    by_year: dict = defaultdict(lambda: {"count": 0, "amount": 0.0})
    inst_stats: dict = defaultdict(lambda: {"name": "", "institution_id": 0, "count": 0, "amount": 0.0})
    for c in contracts:
        year = str(c.award_date.year) if c.award_date else "Sin fecha"
        by_year[year]["count"] += 1
        by_year[year]["amount"] += float(c.amount or 0)
        if c.institution_id:
            inst_stats[c.institution_id]["institution_id"] = c.institution_id
            inst_stats[c.institution_id]["name"] = c.institution.name if c.institution else ""
            inst_stats[c.institution_id]["count"] += 1
            inst_stats[c.institution_id]["amount"] += float(c.amount or 0)

    open_anomalies = (
        db.query(Anomaly)
        .join(Contract, Anomaly.contract_id == Contract.id)
        .filter(Contract.supplier_id == supplier_id, Anomaly.status == "open")
        .count()
    )

    return {
        "id": supplier.id,
        "name": supplier.name,
        "normalized_name": supplier.normalized_name,
        "tax_id": supplier.tax_id,
        "contract_count": len(contracts),
        "total_amount": sum(float(c.amount or 0) for c in contracts),
        "open_anomalies": open_anomalies,
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "institutions": sorted(inst_stats.values(), key=lambda x: x["amount"], reverse=True)[:20],
        "contracts": [_serialize_contract(c) for c in contracts[:50]],
    }


@app.get("/institutions")
def institutions_list(db: Session = Depends(get_db)) -> list[dict]:
    from models.institution import Institution
    return [{"id": i.id, "name": i.name}
            for i in db.query(Institution).order_by(Institution.name).all()]


@app.get("/institutions/{institution_id}/profile")
def institution_profile(institution_id: int, db: Session = Depends(get_db)) -> dict:
    from collections import defaultdict
    from models.anomaly import Anomaly
    from models.contract import Contract
    from models.institution import Institution
    from services.contract_service import _serialize_contract

    institution = db.get(Institution, institution_id)
    if institution is None:
        raise HTTPException(status_code=404, detail="Institución no encontrada")

    contracts = (
        db.query(Contract)
        .filter(Contract.institution_id == institution_id, Contract.is_demo.is_(False))
        .order_by(Contract.award_date.desc())
        .all()
    )

    by_year: dict = defaultdict(lambda: {"count": 0, "amount": 0.0})
    sup_stats: dict = defaultdict(lambda: {"name": "", "supplier_id": 0, "count": 0, "amount": 0.0})
    for c in contracts:
        year = str(c.award_date.year) if c.award_date else "Sin fecha"
        by_year[year]["count"] += 1
        by_year[year]["amount"] += float(c.amount or 0)
        if c.supplier_id:
            sup_stats[c.supplier_id]["supplier_id"] = c.supplier_id
            sup_stats[c.supplier_id]["name"] = c.supplier.name if c.supplier else ""
            sup_stats[c.supplier_id]["count"] += 1
            sup_stats[c.supplier_id]["amount"] += float(c.amount or 0)

    open_anomalies = (
        db.query(Anomaly)
        .join(Contract, Anomaly.contract_id == Contract.id)
        .filter(Contract.institution_id == institution_id, Anomaly.status == "open")
        .count()
    )

    return {
        "id": institution.id,
        "name": institution.name,
        "normalized_name": institution.normalized_name,
        "contract_count": len(contracts),
        "total_amount": sum(float(c.amount or 0) for c in contracts),
        "open_anomalies": open_anomalies,
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "suppliers": sorted(sup_stats.values(), key=lambda x: x["amount"], reverse=True)[:20],
        "contracts": [_serialize_contract(c) for c in contracts[:50]],
    }


@app.post("/merge-requests")
def create_merge_request(
    keep_supplier_id: int = Query(...),
    merge_supplier_name: str = Query(...),
    note: str | None = Query(default=None),
    actor: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    import json as _json
    from datetime import datetime, timezone
    from models.supplier import Supplier

    supplier = db.get(Supplier, keep_supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    entry = {
        "request_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:18],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "keep_supplier_id": keep_supplier_id,
        "keep_supplier_name": supplier.name,
        "merge_supplier_name": merge_supplier_name,
        "note": note or "",
        "status": "pending",
    }

    merge_file = Path("data/processed/merge_requests.json")
    merge_file.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if merge_file.exists():
        try:
            existing = _json.loads(merge_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(entry)
    merge_file.write_text(_json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    from services.audit_service import record_audit
    record_audit(
        db,
        action="supplier.merge_requested",
        actor=actor,
        target_type="supplier",
        target_id=keep_supplier_id,
        details={"merge_supplier_name": merge_supplier_name, "request_id": entry["request_id"]},
    )
    db.commit()
    return {"status": "solicitud_registrada", "request_id": entry["request_id"]}


@app.get("/contracts/{contract_id}")
def contract_detail(contract_id: int, db: Session = Depends(get_db)) -> dict:
    from models.contract import Contract
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    from services.contract_service import _serialize_contract
    return _serialize_contract(contract)


@app.get("/contracts/{contract_id}/events")
def contract_events(contract_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_contract_events(db=db, contract_id=contract_id)


@app.get("/history/metrics")
def history_metrics(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func
    from models.contract import Contract
    from models.contract_event import ContractEvent
    changed_events = db.query(ContractEvent).join(Contract).filter(
        Contract.is_demo.is_(False),
        ContractEvent.event_type == "field_changed",
    )
    latest = changed_events.with_entities(func.max(ContractEvent.detected_at)).scalar()
    return {
        "field_changed_events": changed_events.count(),
        "contracts_with_changes": changed_events.with_entities(
            func.count(func.distinct(ContractEvent.contract_id))
        ).scalar() or 0,
        "latest_change_at": latest.isoformat() if latest else None,
        "history_demonstrated": changed_events.count() > 0,
    }


@app.get("/anomalies")
def anomalies(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_anomalies(db=db, status=status, severity=severity)


@app.get("/alerts.rss")
def confirmed_alerts_rss(db: Session = Depends(get_db)) -> Response:
    from html import escape
    from models.anomaly import Anomaly
    rows = db.query(Anomaly).filter(Anomaly.status == "confirmed").order_by(
        Anomaly.reviewed_at.desc(), Anomaly.id.desc(),
    ).limit(50).all()
    items = []
    for anomaly in rows:
        link = f"/anomalies/{anomaly.id}"
        reviewed = anomaly.reviewed_at.isoformat() if anomaly.reviewed_at else ""
        items.append(
            "<item>"
            f"<title>{escape(anomaly.anomaly_type)} — contrato {anomaly.contract_id}</title>"
            f"<link>{escape(link)}</link>"
            f"<guid>anomaly-{anomaly.id}</guid>"
            f"<description>{escape(anomaly.reason)}</description>"
            f"<pubDate>{escape(reviewed)}</pubDate>"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        '<title>Monitor de Gasto Público — alertas confirmadas</title>'
        '<description>Solo alertas que completaron revisión humana.</description>'
        '<link>/</link>' + "".join(items) + '</channel></rss>'
    )
    return Response(content=xml, media_type="application/rss+xml")


class AlertSubscriptionInput(BaseModel):
    channel: str
    destination: str
    secret: str | None = None
    anomaly_type: str | None = None
    active: bool = True


@app.get("/alert-subscriptions")
def alert_subscriptions(
    db: Session = Depends(get_db),
    _actor: str = Depends(require_admin),
) -> list[dict]:
    from models.alert_subscription import AlertSubscription
    rows = db.query(AlertSubscription).order_by(AlertSubscription.id.desc()).all()
    return [{
        "id": row.id,
        "channel": row.channel,
        "destination": row.destination,
        "anomaly_type": row.anomaly_type,
        "active": row.active,
        "created_at": row.created_at,
    } for row in rows]


@app.post("/alert-subscriptions")
def create_alert_subscription(
    body: AlertSubscriptionInput,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
) -> dict:
    from models.alert_subscription import AlertSubscription
    from services.audit_service import record_audit
    channel = body.channel.lower().strip()
    destination = body.destination.strip()
    if channel not in {"email", "webhook"}:
        raise HTTPException(status_code=422, detail="Canal debe ser email o webhook")
    if channel == "email" and "@" not in destination:
        raise HTTPException(status_code=422, detail="Correo inválido")
    if channel == "webhook" and not destination.startswith("https://"):
        raise HTTPException(status_code=422, detail="Webhook debe usar HTTPS")
    if channel == "webhook" and not body.secret:
        raise HTTPException(status_code=422, detail="Webhook requiere secreto HMAC")
    item = AlertSubscription(
        channel=channel,
        destination=destination,
        secret=body.secret,
        anomaly_type=body.anomaly_type,
        active=body.active,
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        action="alert_subscription.created",
        actor=actor,
        target_type="alert_subscription",
        target_id=item.id,
        details={"channel": channel, "anomaly_type": body.anomaly_type},
    )
    db.commit()
    return {"id": item.id, "channel": item.channel, "active": item.active}


@app.post("/alerts/dispatch")
def dispatch_alerts(
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
) -> dict:
    from services.alert_dispatch_service import dispatch_confirmed_alerts
    from services.audit_service import record_audit
    result = dispatch_confirmed_alerts(db)
    record_audit(
        db,
        action="alerts.dispatched",
        actor=actor,
        target_type="alert_delivery",
        details=result,
    )
    db.commit()
    return result


@app.get("/anomalies/{anomaly_id}")
def anomaly_detail(anomaly_id: int, db: Session = Depends(get_db)) -> dict:
    result = get_anomaly(db, anomaly_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Anomalía no encontrada")
    return result


@app.post("/admin/anomalies/detect")
def detect_anomalies(
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
) -> dict:
    from services.audit_service import record_audit
    count = run_detection(db)
    record_audit(
        db, action="anomalies.detected", actor=actor,
        target_type="anomaly", details={"new_anomalies": count},
    )
    db.commit()
    return {"new_anomalies": count}


class IngestRequest(BaseModel):
    search_terms: list[str]
    years: list[int] = [2024, 2025]
    limit: int = 50
    detail: bool = True


class AnomalyUpdate(BaseModel):
    status: str
    editorial_note: str | None = None
    reviewer: str | None = None
    evidence_url: str | None = None


VALID_STATUSES = {"open", "confirmed", "discarded", "indeterminate", "under_review"}


@app.patch("/anomalies/{anomaly_id}")
def patch_anomaly(
    anomaly_id: int,
    body: AnomalyUpdate,
    db: Session = Depends(get_db),
    _actor: str = Depends(require_admin),
) -> dict:
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {VALID_STATUSES}")
    try:
        result = update_anomaly_status(
            db,
            anomaly_id,
            body.status,
            body.editorial_note,
            reviewer=body.reviewer,
            evidence_url=body.evidence_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return result


@app.get("/review-metrics")
def anomaly_review_metrics(db: Session = Depends(get_db)) -> dict:
    from services.anomaly_service import review_metrics
    return review_metrics(db, target=100)


class CorrectionRequestInput(BaseModel):
    contract_id: int | None = None
    requester_name: str | None = None
    requester_contact: str | None = None
    reason: str
    evidence_url: str | None = None


class CorrectionResolution(BaseModel):
    status: str
    resolution_note: str


@app.post("/correction-requests")
def submit_correction_request(
    body: CorrectionRequestInput,
    db: Session = Depends(get_db),
) -> dict:
    from models.contract import Contract
    from models.correction_request import CorrectionRequest
    from services.audit_service import record_audit

    if len(body.reason.strip()) < 20:
        raise HTTPException(status_code=422, detail="La solicitud necesita una explicación de al menos 20 caracteres")
    if body.contract_id is not None and db.get(Contract, body.contract_id) is None:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    request = CorrectionRequest(
        contract_id=body.contract_id,
        requester_name=body.requester_name,
        requester_contact=body.requester_contact,
        reason=body.reason.strip(),
        evidence_url=body.evidence_url,
    )
    db.add(request)
    db.flush()
    record_audit(
        db,
        action="correction.requested",
        actor="public",
        target_type="correction_request",
        target_id=request.id,
        details={"contract_id": body.contract_id},
    )
    db.commit()
    return {"id": request.id, "status": request.status, "created_at": request.created_at}


@app.get("/correction-requests")
def list_correction_requests(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _actor: str = Depends(require_admin),
) -> list[dict]:
    from models.correction_request import CorrectionRequest
    query = db.query(CorrectionRequest)
    if status:
        query = query.filter(CorrectionRequest.status == status)
    return [{
        "id": item.id,
        "contract_id": item.contract_id,
        "requester_name": item.requester_name,
        "requester_contact": item.requester_contact,
        "reason": item.reason,
        "evidence_url": item.evidence_url,
        "status": item.status,
        "resolution_note": item.resolution_note,
        "created_at": item.created_at,
        "resolved_at": item.resolved_at,
    } for item in query.order_by(CorrectionRequest.id.desc()).all()]


@app.patch("/correction-requests/{request_id}")
def resolve_correction_request(
    request_id: int,
    body: CorrectionResolution,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
) -> dict:
    from datetime import datetime, timezone
    from models.correction_request import CorrectionRequest
    from services.audit_service import record_audit
    if body.status not in {"under_review", "accepted", "rejected"}:
        raise HTTPException(status_code=422, detail="Estado de rectificación inválido")
    item = db.get(CorrectionRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    item.status = body.status
    item.resolution_note = body.resolution_note.strip()
    item.resolved_at = datetime.now(timezone.utc) if body.status in {"accepted", "rejected"} else None
    record_audit(
        db,
        action="correction.resolved",
        actor=actor,
        target_type="correction_request",
        target_id=item.id,
        details={"status": item.status},
    )
    db.commit()
    return {"id": item.id, "status": item.status, "resolved_at": item.resolved_at}


class ProcurementRuleInput(BaseModel):
    year: int
    procedure_type: str
    threshold: float
    operator: str = "lt"
    currency: str = "USD"
    legal_reference: str
    source_url: str
    active: bool = True


@app.get("/procurement-rules")
def procurement_rules(db: Session = Depends(get_db)) -> list[dict]:
    from models.procurement_rule import ProcurementRule
    from services.procurement_rule_service import serialize_rule
    rows = db.query(ProcurementRule).order_by(
        ProcurementRule.year.desc(), ProcurementRule.procedure_type,
    ).all()
    return [serialize_rule(row) for row in rows]


@app.post("/procurement-rules")
def upsert_procurement_rule(
    body: ProcurementRuleInput,
    db: Session = Depends(get_db),
    actor: str = Depends(require_admin),
) -> dict:
    from decimal import Decimal
    from models.procurement_rule import ProcurementRule
    from services.audit_service import record_audit
    from services.procurement_rule_service import normalize_procedure_type, serialize_rule

    if body.threshold <= 0:
        raise HTTPException(status_code=422, detail="El umbral debe ser positivo")
    if body.operator not in {"lt", "lte"}:
        raise HTTPException(status_code=422, detail="Operador debe ser lt o lte")
    if not body.source_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="La regla requiere una fuente HTTPS")
    procedure_type = normalize_procedure_type(body.procedure_type) or "*"
    rule = db.query(ProcurementRule).filter(
        ProcurementRule.year == body.year,
        ProcurementRule.procedure_type == procedure_type,
    ).first()
    if rule is None:
        rule = ProcurementRule(year=body.year, procedure_type=procedure_type)
        db.add(rule)
    rule.threshold = Decimal(str(body.threshold))
    rule.operator = body.operator
    rule.currency = body.currency.upper()
    rule.legal_reference = body.legal_reference.strip()
    rule.source_url = body.source_url.strip()
    rule.active = body.active
    db.flush()
    record_audit(
        db,
        action="procurement_rule.upserted",
        actor=actor,
        target_type="procurement_rule",
        target_id=rule.id,
        details={"year": rule.year, "procedure_type": rule.procedure_type},
    )
    db.commit()
    db.refresh(rule)
    return serialize_rule(rule)


PREMIUM_TOKEN = settings.premium_token


@app.post("/ingest")
def ingest_on_demand(
    body: IngestRequest,
    db: Session = Depends(get_db),
    x_premium_token: str | None = Header(default=None),
) -> dict:
    if not PREMIUM_TOKEN or x_premium_token != PREMIUM_TOKEN:
        raise HTTPException(status_code=403, detail="Token premium requerido")
    if len(body.search_terms) > 10:
        raise HTTPException(status_code=422, detail="Maximo 10 terminos por ingesta")
    if body.limit > 200:
        raise HTTPException(status_code=422, detail="Maximo 200 contratos por ingesta")

    if _ingest_lock.locked():
        raise HTTPException(status_code=409, detail="Ya hay una ingesta en curso, intenta en unos minutos")

    from scripts.scheduler import _run_ingestion

    def _bg_ingest() -> None:
        with _ingest_lock:
            _run_ingestion(
                search_terms=body.search_terms,
                years=body.years,
                limit=body.limit,
                detail=body.detail,
                franja_name="premium_on_demand",
                detail_delay=0.5,
            )

    thread = threading.Thread(target=_bg_ingest, daemon=True)
    thread.start()

    from services.audit_service import record_audit
    record_audit(
        db,
        action="ingestion.started",
        actor="premium_token",
        target_type="ingestion_run",
        details={"years": body.years, "terms": body.search_terms, "limit": body.limit},
    )
    db.commit()

    return {
        "status": "ingesta_iniciada",
        "search_terms": body.search_terms,
        "years": body.years,
        "limit": body.limit,
        "detail": body.detail,
    }


@app.get("/ingestion-runs")
def ingestion_runs(db: Session = Depends(get_db)) -> list[dict]:
    from models.ingestion_run import IngestionRun
    runs = db.query(IngestionRun).order_by(IngestionRun.id.desc()).limit(20).all()
    return [
        {
            "id": r.id,
            "source_name": r.source_name,
            "status": r.status,
            "records_fetched": r.records_fetched,
            "records_new": r.records_new,
            "parameters": r.parameters,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@app.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    from models.anomaly import Anomaly
    from models.contract import Contract
    from models.institution import Institution
    from models.supplier import Supplier

    from sqlalchemy import func
    total_contracts = db.query(Contract).filter(Contract.is_demo.is_(False)).count()
    total_institutions = (
        db.query(Institution)
        .join(Contract, Contract.institution_id == Institution.id)
        .filter(Contract.is_demo.is_(False))
        .distinct()
        .count()
    )
    total_suppliers = (
        db.query(Supplier)
        .join(Contract, Contract.supplier_id == Supplier.id)
        .filter(Contract.is_demo.is_(False))
        .distinct()
        .count()
    )
    open_anomalies = db.query(Anomaly).filter(Anomaly.status == "open").count()
    total_anomalies = db.query(Anomaly).count()
    total_amount = db.query(func.sum(Contract.amount)).filter(Contract.is_demo.is_(False)).scalar() or 0
    return {
        "total_contracts": total_contracts,
        "total_institutions": total_institutions,
        "total_suppliers": total_suppliers,
        "open_anomalies": open_anomalies,
        "total_anomalies": total_anomalies,
        "total_amount": float(total_amount),
    }


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_frontend() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
