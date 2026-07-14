"""Load verified SERCOP infima-cuantia thresholds for 2015-2025."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from models.procurement_rule import ProcurementRule
from services.audit_service import record_audit
from services.procurement_rule_service import normalize_procedure_type


RULES = [
    (2015, "7263.42", "lte", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2015/"),
    (2016, "5967.02", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2016/"),
    (2017, "5967.02", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2017/"),
    (2018, "6970.67", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2018/"),
    (2019, "7105.88", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2019/"),
    (2020, "7099.68", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-2020/"),
    (2021, "6416.07", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2021/"),
    (2022, "6779.95", "lt", "https://portal.compraspublicas.gob.ec/sercop/montos-de-contratacion-publica-2022/"),
    (2023, "6300.57", "lte", "https://portal.compraspublicas.gob.ec/sercop/wp-content/uploads/2023/01/montos_contratacion_2023.pdf"),
    (2024, "6659.36", "lte", "https://portal.compraspublicas.gob.ec/sercop/wp-content/uploads/2024/01/montos_contratacion_2024.pdf"),
    (2025, "7212.60", "lte", "https://portal.compraspublicas.gob.ec/sercop/wp-content/uploads/2025/01/micro_montos_08_01_2025-2_compressed.pdf"),
]


def seed(apply: bool) -> dict:
    init_db()
    procedure = normalize_procedure_type("Infima Cuantia")
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    with SessionLocal() as db:
        for year, amount, operator, source_url in RULES:
            rule = db.query(ProcurementRule).filter(
                ProcurementRule.year == year,
                ProcurementRule.procedure_type == procedure,
            ).first()
            desired = Decimal(amount)
            if rule is None:
                rule = ProcurementRule(
                    year=year,
                    procedure_type=procedure,
                    threshold=desired,
                    operator=operator,
                    currency="USD",
                    legal_reference="Tabla oficial de montos de contratación pública SERCOP",
                    source_url=source_url,
                    active=True,
                )
                db.add(rule)
                stats["created"] += 1
            elif (
                Decimal(rule.threshold) != desired
                or rule.operator != operator
                or rule.source_url != source_url
            ):
                rule.threshold = desired
                rule.operator = operator
                rule.source_url = source_url
                rule.legal_reference = "Tabla oficial de montos de contratación pública SERCOP"
                rule.active = True
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        if apply:
            record_audit(
                db,
                action="procurement_rules.official_seed",
                actor="official-rule-seed",
                target_type="procurement_rule",
                details={**stats, "years": [row[0] for row in RULES]},
            )
            db.commit()
        else:
            db.rollback()
    stats["mode"] = "apply" if apply else "dry-run"
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(seed(args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
