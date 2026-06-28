from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    procedure_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_origin: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_payload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    last_raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"), nullable=True)

    institution = relationship("Institution", back_populates="contracts")
    supplier = relationship("Supplier", back_populates="contracts")
    last_raw_record = relationship("RawRecord", foreign_keys=[last_raw_record_id])
