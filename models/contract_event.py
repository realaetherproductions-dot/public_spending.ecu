from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ContractEvent(Base):
    __tablename__ = "contract_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32))
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    contract = relationship("Contract", backref="events")
    raw_record = relationship("RawRecord")
