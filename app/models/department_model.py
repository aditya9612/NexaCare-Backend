from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    department_id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int | None] = mapped_column(
        ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    department_code: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    department_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    # Existing relations
    appointments = relationship("Appointment", back_populates="department")
    doctors = relationship("Doctor", back_populates="department")
    nurses = relationship("Nurse", back_populates="department")

    # New relations
    lab_tests = relationship("LabTest", back_populates="department")
    test_orders = relationship("TestOrder", back_populates="department")
    inventory_items = relationship("InventoryItem", back_populates="department")

    @property
    def name(self) -> str:
        return self.department_name

    @name.setter
    def name(self, value: str) -> None:
        self.department_name = value

    @property
    def id(self) -> int:
        return self.department_id

    @id.setter
    def id(self, value: int) -> None:
        self.department_id = value
