from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("source_name", "source_id", "payload_hash", name="uq_raw_source_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    source_name: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(256), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)

    ingestion_run = relationship("IngestionRun", back_populates="raw_records")
    contract = relationship("Contract", foreign_keys=[contract_id])
