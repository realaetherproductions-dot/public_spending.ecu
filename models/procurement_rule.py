from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcurementRule(Base):
    __tablename__ = "procurement_rules"
    __table_args__ = (
        UniqueConstraint("year", "procedure_type", name="uq_procurement_rule_year_procedure"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(index=True)
    procedure_type: Mapped[str] = mapped_column(String(128), index=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    operator: Mapped[str] = mapped_column(String(4), default="lt")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    legal_reference: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
