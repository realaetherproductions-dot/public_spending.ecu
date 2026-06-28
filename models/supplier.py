from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    contracts = relationship("Contract", back_populates="supplier")

