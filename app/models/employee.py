from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum
from app.models.user import User


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Employee(TimestampMixin, Base):
    """HR record of a staff member. Login accounts are optional (a cleaner may not need one)."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    designation: Mapped[str] = mapped_column(String(100))
    join_date: Mapped[date]
    date_of_birth: Mapped[date | None]
    gender: Mapped[Gender | None] = mapped_column(str_enum(Gender))
    # nullable + unique, so any number of employees can be without one
    nid: Mapped[str | None] = mapped_column(String(30), unique=True)
    address: Mapped[str | None] = mapped_column(String(255))
    father_name: Mapped[str | None] = mapped_column(String(100))
    mother_name: Mapped[str | None] = mapped_column(String(100))
    spouse_name: Mapped[str | None] = mapped_column(String(100))
    monthly_salary: Mapped[Decimal | None]
    image_key: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    user: Mapped[User | None] = relationship(lazy="raise")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
