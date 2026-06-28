from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url.startswith("sqlite:///./"):
    db_path = Path(settings.database_url.replace("sqlite:///./", "", 1))
    db_path.parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from models.anomaly import Anomaly
    from models.contract import Contract
    from models.contract_event import ContractEvent
    from models.ingestion_run import IngestionRun
    from models.institution import Institution
    from models.raw_record import RawRecord
    from models.supplier import Supplier

    _ = (Anomaly, Contract, ContractEvent, IngestionRun, Institution, RawRecord, Supplier)
    Base.metadata.create_all(bind=engine)
    _ensure_contract_columns()


def _ensure_contract_columns() -> None:
    inspector = inspect(engine)
    if "contracts" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("contracts")}
    statements = []
    if "data_origin" not in existing:
        statements.append("ALTER TABLE contracts ADD COLUMN data_origin VARCHAR(64) DEFAULT 'unknown'")
    if "is_demo" not in existing:
        statements.append("ALTER TABLE contracts ADD COLUMN is_demo BOOLEAN DEFAULT 0")
    if "last_raw_record_id" not in existing:
        statements.append("ALTER TABLE contracts ADD COLUMN last_raw_record_id INTEGER REFERENCES raw_records(id)")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
