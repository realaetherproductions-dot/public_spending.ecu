from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AnomalyReview(Base):
    __tablename__ = "anomaly_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reviewer: Mapped[str] = mapped_column(String(128), index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    anomaly = relationship("Anomaly", backref="reviews")
