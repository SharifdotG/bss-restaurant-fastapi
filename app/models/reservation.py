import secrets
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum
from app.models.table import DiningTable
from app.models.user import User


class ReservationStatus(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    SEATED = "seated"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DECLINED = "declined"
    NO_SHOW = "no_show"


# a booking only keeps its table while it's confirmed or the guests are sitting there
HOLDS_TABLE = (ReservationStatus.CONFIRMED, ReservationStatus.SEATED)

NEXT_STATUSES: dict[ReservationStatus, tuple[ReservationStatus, ...]] = {
    ReservationStatus.REQUESTED: (
        ReservationStatus.CONFIRMED,
        ReservationStatus.DECLINED,
        ReservationStatus.CANCELLED,
    ),
    ReservationStatus.CONFIRMED: (
        ReservationStatus.SEATED,
        ReservationStatus.NO_SHOW,
        ReservationStatus.CANCELLED,
    ),
    ReservationStatus.SEATED: (ReservationStatus.COMPLETED,),
    ReservationStatus.COMPLETED: (),
    ReservationStatus.CANCELLED: (),
    ReservationStatus.DECLINED: (),
    ReservationStatus.NO_SHOW: (),
}


class ReservationSource(StrEnum):
    # taken by staff, on the phone or at the door
    STAFF = "staff"
    ONLINE = "online"


def new_tracking_code() -> str:
    return secrets.token_urlsafe(12)


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("party_size BETWEEN 1 AND 50", name="party_size_range"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint(
            "status NOT IN ('confirmed', 'seated') OR table_id IS NOT NULL",
            name="confirmed_has_table",
        ),
        Index("ix_reservations_status_starts_at", "status", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_code: Mapped[str] = mapped_column(String(24), unique=True, default=new_tracking_code)
    source: Mapped[ReservationSource] = mapped_column(str_enum(ReservationSource))
    status: Mapped[ReservationStatus] = mapped_column(str_enum(ReservationStatus))
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("dining_tables.id", ondelete="RESTRICT"), index=True
    )
    party_size: Mapped[int]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    customer_email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    table: Mapped[DiningTable | None] = relationship(lazy="raise")
    created_by: Mapped[User | None] = relationship(lazy="raise")

    @property
    def next_statuses(self) -> list[ReservationStatus]:
        return list(NEXT_STATUSES[self.status])

    @property
    def minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


# the database itself refuses two bookings on one table at overlapping times, so two
# people booking the last table at the same moment can't both get it. needs btree_gist
# for the "=" on table_id
Reservation.__table__.append_constraint(
    ExcludeConstraint(
        (Reservation.table_id, "="),
        (func.tstzrange(Reservation.starts_at, Reservation.ends_at), "&&"),
        name="ex_reservations_no_double_booking",
        using="gist",
        where="status IN ('confirmed', 'seated')",
    )
)
