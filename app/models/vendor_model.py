from sqlalchemy import String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin


class Vendor(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    vendor_type: Mapped[str] = mapped_column(String(50), default="inventory", index=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    expenses: Mapped[list["Expense"]] = relationship("Expense", back_populates="vendor")
    payments: Mapped[list["VendorPayment"]] = relationship("VendorPayment", back_populates="vendor")
    items: Mapped[list["InventoryItem"]] = relationship("InventoryItem", back_populates="vendor")
