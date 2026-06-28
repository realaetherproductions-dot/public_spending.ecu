"""Scheduler de ingesta automatica — 3 franjas diarias.

Franja 1 (02:00) — Barrido historico: un sector + un ano por corrida, rotativo.
Franja 2 (10:00) — Contratos recientes: terminos genericos para capturar lo nuevo.
Franja 3 (18:00) — Obras emblematicas: proyectos de alto interes periodistico.

Uso:
    python scripts/scheduler.py --franja 1        # ejecutar franja 1 ahora
    python scripts/scheduler.py --franja 2
    python scripts/scheduler.py --franja 3
    python scripts/scheduler.py --daemon           # corre las 3 franjas en horario
    python scripts/scheduler.py --estado           # ver progreso del barrido historico
"""

import argparse
import json
import logging
import sys
import time
import threading
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from collectors.sercop_client import SercopClient
from models.ingestion_run import IngestionRun
from pipelines.ingest_contracts import ingest_contract_records

# ── Logging a consola + archivo ───────────────────────────────

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "scheduler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("scheduler")

# ── Configuracion de franjas ────────────────────────────────────

SECTORES = [
    "salud", "vialidad", "educacion", "seguridad",
    "mantenimiento", "emergencia", "agua", "construccion",
    "consultoria", "tecnologia", "alimentacion", "transporte",
]

ANOS_HISTORICOS = list(range(2015, 2026))

TERMINOS_RECIENTES = [
    "contrato", "servicio", "adquisicion", "obra",
    "subasta", "catalogo", "cotizacion", "menor cuantia",
]

OBRAS_EMBLEMATICAS = [
    "Coca Codo Sinclair",
    "carcel del encuentro",
    "escuelas del milenio",
    "Hospital de Pedernales",
    "Refineria del Pacifico",
    "Metro de Quito",
    "Hidroelectrica Toachi Pilaton",
    "Poliducto Pascuales",
    "Ciudad del Conocimiento Yachay",
    "Soterramiento Quito",
]

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "processed" / "scheduler_state.json"


# ── Estado persistente para rotacion de franja 1 ────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"sector_index": 0, "year_index": 0, "last_run": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Funcion comun de ingesta ────────────────────────────────────

def _run_ingestion(
    search_terms: list[str],
    years: list[int],
    limit: int | None,
    detail: bool,
    franja_name: str,
    detail_delay: float = 0.5,
) -> dict:
    init_db()
    client = SercopClient()
    stats = {"fetched": 0, "inserted": 0, "errors": 0}

    with SessionLocal() as db:
        run = IngestionRun(
            source_name="sercop_ocds",
            parameters=json.dumps({
                "franja": franja_name,
                "search": search_terms,
                "years": years,
                "limit": limit,
                "detail": detail,
            }, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        log.info(f"[Franja {franja_name}] Run #{run_id} — terminos={search_terms} anos={years} detail={detail}")

        try:
            records = client.fetch_contracts_by_keyword(
                years=years,
                search=search_terms,
                limit=limit,
            )
            stats["fetched"] = len(records)
            log.info(f"  Encontrados {len(records)} contratos unicos")

            if detail and records:
                log.info(f"  Enriqueciendo con detalle ({len(records)} llamadas)...")
                enriched = []
                for i, record in enumerate(records, 1):
                    try:
                        enriched.append(client.enrich_record(record))
                    except Exception as e:
                        log.warning(f"  Error en detalle {i}: {e}")
                        enriched.append(record)
                        stats["errors"] += 1
                    if i % 10 == 0 or i == len(records):
                        log.info(f"  detalle {i}/{len(records)}")
                    time.sleep(detail_delay)
                records = enriched

            inserted = ingest_contract_records(
                db, records, source_name="sercop_ocds", is_demo=False, ingestion_run_id=run_id,
            )
            stats["inserted"] = inserted

            run.status = "completed"
            run.records_fetched = len(records)
            run.records_new = inserted
            run.finished_at = datetime.utcnow()
            db.commit()

            log.info(f"  Resultado: {len(records)} descargados, {inserted} nuevos")

            # Deteccion de anomalias automatica tras cada ingesta
            try:
                from pipelines.detect_anomalies import detect_contract_anomalies
                new_anomalies = detect_contract_anomalies(db, detection_run_id=run_id)
                log.info(f"  Anomalias: {len(new_anomalies)} nuevas detectadas")
            except Exception as e:
                log.error(f"  Error en deteccion de anomalias: {e}")

        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            run.finished_at = datetime.utcnow()
            db.commit()
            log.error(f"  ERROR en ingesta: {exc}", exc_info=True)
            stats["errors"] += 1

    return stats


# ── Franja 1: Barrido historico (rotativo) ──────────────────────

def franja_historico() -> dict:
    state = _load_state()
    si = state["sector_index"] % len(SECTORES)
    yi = state["year_index"] % len(ANOS_HISTORICOS)

    sector = SECTORES[si]
    year = ANOS_HISTORICOS[yi]

    log.info(f"=== FRANJA 1: Barrido historico — {sector!r} {year} ===")
    log.info(f"    (posicion {si+1}/{len(SECTORES)} sectores, {yi+1}/{len(ANOS_HISTORICOS)} anos)")

    result = _run_ingestion(
        search_terms=[sector],
        years=[year],
        limit=500,
        detail=False,
        franja_name="historico",
    )

    state["year_index"] = yi + 1
    if state["year_index"] >= len(ANOS_HISTORICOS):
        state["year_index"] = 0
        state["sector_index"] = si + 1
    state["last_run"]["franja_1"] = datetime.utcnow().isoformat()
    _save_state(state)

    total = len(SECTORES) * len(ANOS_HISTORICOS)
    done = si * len(ANOS_HISTORICOS) + yi + 1
    log.info(f"    Progreso total: {done}/{total} combinaciones ({100*done//total}%)")
    return result


# ── Franja 2: Contratos recientes ──────────────────────────────

def franja_recientes() -> dict:
    current_year = date.today().year
    log.info(f"=== FRANJA 2: Contratos recientes — {current_year} ===")

    result = _run_ingestion(
        search_terms=TERMINOS_RECIENTES,
        years=[current_year, current_year - 1],
        limit=200,
        detail=False,
        franja_name="recientes",
    )

    state = _load_state()
    state["last_run"]["franja_2"] = datetime.utcnow().isoformat()
    _save_state(state)
    return result


# ── Franja 3: Obras emblematicas ───────────────────────────────

def franja_emblematicas() -> dict:
    log.info("=== FRANJA 3: Obras emblematicas ===")

    result = _run_ingestion(
        search_terms=OBRAS_EMBLEMATICAS,
        years=list(range(2008, date.today().year + 1)),
        limit=None,
        detail=False,
        franja_name="emblematicas",
    )

    state = _load_state()
    state["last_run"]["franja_3"] = datetime.utcnow().isoformat()
    _save_state(state)
    return result


# ── Estado del barrido ─────────────────────────────────────────

def mostrar_estado() -> None:
    state = _load_state()
    si = state["sector_index"] % len(SECTORES)
    yi = state["year_index"] % len(ANOS_HISTORICOS)
    total = len(SECTORES) * len(ANOS_HISTORICOS)
    done = si * len(ANOS_HISTORICOS) + yi

    print("=== Estado del Scheduler ===")
    print(f"Barrido historico: {done}/{total} combinaciones ({100*done//total}%)")
    print(f"Proxima corrida: sector={SECTORES[si]!r} ano={ANOS_HISTORICOS[yi]}")
    print(f"Sectores: {', '.join(SECTORES)}")
    print(f"Anos: {ANOS_HISTORICOS[0]}-{ANOS_HISTORICOS[-1]}")
    for franja, ts in state.get("last_run", {}).items():
        print(f"Ultima ejecucion {franja}: {ts}")
    print(f"\nLog completo: {LOG_FILE}")


def generar_reporte(horas: int = 24) -> None:
    """Genera un reporte de las ultimas N horas de ingesta."""
    from models.anomaly import Anomaly
    from models.contract import Contract
    from sqlalchemy import func

    init_db()
    db = SessionLocal()

    cutoff = datetime.utcnow().replace(microsecond=0)
    desde = datetime(cutoff.year, cutoff.month, cutoff.day, cutoff.hour, cutoff.minute, cutoff.second)
    from datetime import timedelta
    desde = cutoff - timedelta(hours=horas)

    runs = db.query(IngestionRun).filter(IngestionRun.started_at >= desde).order_by(IngestionRun.id).all()
    total_contracts = db.query(Contract).count()
    total_amount = db.query(func.sum(Contract.amount)).scalar() or 0
    total_anomalies = db.query(Anomaly).count()
    open_anomalies = db.query(Anomaly).filter(Anomaly.status == "open").count()

    print(f"{'='*60}")
    print(f"  REPORTE DE INGESTA — Ultimas {horas} horas")
    print(f"  Generado: {cutoff.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*60}")
    print()

    # Resumen global
    print(f"  Base de datos actual:")
    print(f"    Contratos totales:  {total_contracts:,}")
    print(f"    Monto total:        ${float(total_amount):,.2f}")
    print(f"    Anomalias totales:  {total_anomalies:,} ({open_anomalies} abiertas)")
    print()

    if not runs:
        print(f"  No se ejecutaron ingestas en las ultimas {horas} horas.")
        print()
        print(f"  Log completo: {LOG_FILE}")
        db.close()
        return

    # Detalle por corrida
    completed = [r for r in runs if r.status == "completed"]
    failed = [r for r in runs if r.status == "failed"]
    total_fetched = sum(r.records_fetched or 0 for r in runs)
    total_new = sum(r.records_new or 0 for r in runs)

    print(f"  Corridas ejecutadas: {len(runs)}")
    print(f"    Exitosas:  {len(completed)}")
    print(f"    Fallidas:  {len(failed)}")
    print(f"    Contratos descargados: {total_fetched:,}")
    print(f"    Contratos nuevos:      {total_new:,}")
    print()

    for r in runs:
        status_icon = "OK" if r.status == "completed" else "ERROR"
        duration = ""
        if r.started_at and r.finished_at:
            secs = (r.finished_at - r.started_at).total_seconds()
            duration = f" ({secs:.0f}s)"
        print(f"  [{status_icon}] Run #{r.id}{duration}")
        print(f"       Parametros: {r.parameters[:100] if r.parameters else '?'}")
        print(f"       Resultado:  {r.records_fetched or 0} descargados, {r.records_new or 0} nuevos")
        if r.error_message:
            print(f"       Error:      {r.error_message[:200]}")
        print()

    # Errores del log
    if LOG_FILE.exists():
        error_lines = []
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
            if "[ERROR]" in line or "[WARNING]" in line:
                ts_str = line[:19]
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    if ts >= desde:
                        error_lines.append(line)
                except ValueError:
                    pass

        if error_lines:
            print(f"  {'─'*50}")
            print(f"  ERRORES Y ADVERTENCIAS ({len(error_lines)}):")
            for line in error_lines[-20:]:
                print(f"    {line}")
            if len(error_lines) > 20:
                print(f"    ... y {len(error_lines) - 20} mas (ver {LOG_FILE})")
            print()

    print(f"  Log completo: {LOG_FILE}")
    print(f"{'='*60}")
    db.close()


# ── Modo daemon ────────────────────────────────────────────────

def run_daemon() -> None:
    import schedule

    log.info("=== Scheduler iniciado en modo daemon ===")
    log.info(f"Log: {LOG_FILE}")
    log.info("Franjas programadas: 02:00, 10:00, 18:00")
    log.info("Ctrl+C para detener\n")

    def _safe_run(franja_fn, name: str):
        try:
            franja_fn()
        except Exception as e:
            log.error(f"Error critico en {name}: {e}", exc_info=True)

    schedule.every().day.at("02:00").do(_safe_run, franja_historico, "franja_1_historico")
    schedule.every().day.at("10:00").do(_safe_run, franja_recientes, "franja_2_recientes")
    schedule.every().day.at("18:00").do(_safe_run, franja_emblematicas, "franja_3_emblematicas")

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── CLI ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduler de ingesta automatica SERCOP")
    parser.add_argument("--franja", type=int, choices=[1, 2, 3], help="Ejecutar franja especifica")
    parser.add_argument("--daemon", action="store_true", help="Modo daemon (corre en horario)")
    parser.add_argument("--estado", action="store_true", help="Ver progreso del barrido")
    parser.add_argument("--reporte", type=int, nargs="?", const=24, metavar="HORAS",
                        help="Reporte de ultimas N horas (default: 24)")
    args = parser.parse_args()

    if args.reporte is not None:
        generar_reporte(args.reporte)
    elif args.estado:
        mostrar_estado()
    elif args.franja == 1:
        franja_historico()
    elif args.franja == 2:
        franja_recientes()
    elif args.franja == 3:
        franja_emblematicas()
    elif args.daemon:
        try:
            run_daemon()
        except KeyboardInterrupt:
            print("\nScheduler detenido.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
