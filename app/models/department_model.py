from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    department_id: Mapped[int] = mapped_column(primary_key=True, index=True)
    department_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    # Existing relations
    appointments = relationship("Appointment", back_populates="department")
    doctors = relationship("Doctor", back_populates="department")
    nurses = relationship("Nurse", back_populates="department")

    # New relations
    lab_tests = relationship("LabTest", back_populates="department")
    test_orders = relationship("TestOrder", back_populates="department")
    inventory_items = relationship("InventoryItem", back_populates="department")
