from sqlalchemy import ForeignKey, Integer, String, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base
from app.models.hospital_model import Hospital
from app.models.mixins import TimestampMixin


class BillingSetting(Base, TimestampMixin):
    __tablename__ = "billing_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    currency: Mapped[str] = mapped_column(String(10), default="INR", server_default=text("'INR'"))
    currency_symbol: Mapped[str] = mapped_column(String(5), default="₹", server_default=text("'₹'"))
    gst_percentage: Mapped[float] = mapped_column(Float, default=18.0, server_default=text("18.0"))
    
    invoice_prefix: Mapped[str] = mapped_column(String(10), default="BIL", server_default=text("'BIL'"))
    receipt_prefix: Mapped[str] = mapped_column(String(10), default="REC", server_default=text("'REC'"))
    
    default_payment_mode: Mapped[str] = mapped_column(String(20), default="cash", server_default=text("'cash'"))
    round_off_rule: Mapped[str] = mapped_column(String(20), default="nearest", server_default=text("'nearest'"))

    hospital: Mapped["Hospital"] = relationship()
