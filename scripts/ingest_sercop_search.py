import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from collectors.sercop_client import SercopClient
from models.ingestion_run import IngestionRun
from pipelines.ingest_contracts import ingest_contract_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingesta real desde la API OCDS de SERCOP. Soporta multiples "
            "anios y terminos de busqueda, paginacion completa y, "
            "opcionalmente, enriquecimiento con el detalle real de cada "
            "contrato (record?ocid=...)."
        )
    )
    parser.add_argument(
        "--year",
        type=int,
        nargs="+",
        default=[2020],
        help="Uno o mas anios a recorrer, ej: --year 2019 2020 2021",
    )
    parser.add_argument(
        "--search",
        nargs="+",
        default=["agua"],
        help="Uno o mas terminos de busqueda, ej: --search agua salud vialidad",
    )
    parser.add_argument("--buyer", default=None, help="Filtrar por nombre de institucion compradora")
    parser.add_argument("--supplier", default=None, help="Filtrar por nombre de proveedor")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximo de contratos nuevos a traer (usa -1 para no limitar)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Tope de paginas por combinacion anio/termino (por defecto recorre todas)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help=(
            "Llamar record?ocid=... por cada contrato para traer monto, "
            "moneda, adjudicacion y proveedor reales (mas lento, mas completo)"
        ),
    )
    parser.add_argument(
        "--detail-delay",
        type=float,
        default=0.4,
        help="Pausa en segundos entre llamadas de detalle (no saturar la API publica)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    limit = None if args.limit is not None and args.limit < 0 else args.limit

    init_db()
    client = SercopClient()

    params = {
        "years": args.year,
        "search": args.search,
        "buyer": args.buyer,
        "supplier": args.supplier,
        "limit": limit,
        "max_pages": args.max_pages,
        "detail": args.detail,
    }

    with SessionLocal() as db:
        run = IngestionRun(
            source_name="sercop_ocds",
            parameters=json.dumps(params, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        print(
            f"[Run #{run_id}] Buscando en SERCOP -> anios={args.year} terminos={args.search} "
            f"buyer={args.buyer!r} supplier={args.supplier!r} limite={limit if limit is not None else 'sin limite'}"
        )

        try:
            records = client.fetch_contracts_by_keyword(
                years=args.year,
                search=args.search,
                buyer=args.buyer,
                supplier=args.supplier,
                limit=limit,
                max_pages=args.max_pages,
            )
            print(f"Encontrados {len(records)} contratos unicos (deduplicados por ocid)")

            if args.detail:
                print("Enriqueciendo con detalle real (record?ocid=...) ...")
                enriched: list[dict] = []
                for index, record in enumerate(records, start=1):
                    enriched.append(client.enrich_record(record))
                    if index % 5 == 0 or index == len(records):
                        print(f"  detalle {index}/{len(records)}")
                    if args.detail_delay:
                        time.sleep(args.detail_delay)
                records = enriched

            inserted = ingest_contract_records(
                db, records, source_name="sercop_ocds", is_demo=False, ingestion_run_id=run_id,
            )

            run.status = "completed"
            run.records_fetched = len(records)
            run.records_new = inserted
            run.finished_at = datetime.utcnow()
            db.commit()

            print(f"[Run #{run_id}] Fetched {len(records)} real SERCOP records")
            print(f"[Run #{run_id}] Inserted {inserted} new records")

        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            db.commit()
            print(f"[Run #{run_id}] FAILED: {exc}")
            raise


if __name__ == "__main__":
    main()
