from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, case, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, str_enum

CENT = Decimal("0.01")


class DiscountType(StrEnum):
    NONE = "none"
    PERCENTAGE = "percentage"
    FLAT = "flat"


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    image_key: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Food(TimestampMixin, Base):
    __tablename__ = "foods"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_not_negative"),
        CheckConstraint("discount_value >= 0", name="discount_not_negative"),
        CheckConstraint(
            "discount_type <> 'percentage' OR discount_value <= 100", name="percentage_max_100"
        ),
        CheckConstraint(
            "discount_type <> 'flat' OR discount_value <= price", name="flat_max_price"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal]
    discount_type: Mapped[DiscountType] = mapped_column(
        str_enum(DiscountType), default=DiscountType.NONE, server_default=DiscountType.NONE
    )
    discount_value: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    is_available: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_featured: Mapped[bool] = mapped_column(default=False, server_default="false")
    preparation_minutes: Mapped[int | None]
    image_key: Mapped[str | None] = mapped_column(String(255))
    # foods are only soft deleted, old orders still point at them
    deleted_at: Mapped[datetime | None]

    category: Mapped[Category | None] = relationship(lazy="raise")

    @hybrid_property
    def final_price(self) -> Decimal:
        if self.discount_type == DiscountType.PERCENTAGE:
            price = self.price * (100 - self.discount_value) / 100
        elif self.discount_type == DiscountType.FLAT:
            price = self.price - self.discount_value
        else:
            price = self.price
        return max(price, Decimal(0)).quantize(CENT, rounding=ROUND_HALF_UP)

    @final_price.inplace.expression
    @classmethod
    def _final_price_expression(cls):
        return case(
            (
                cls.discount_type == DiscountType.PERCENTAGE,
                func.round(cls.price * (100 - cls.discount_value) / 100, 2),
            ),
            (cls.discount_type == DiscountType.FLAT, cls.price - cls.discount_value),
            else_=cls.price,
        )

    @property
    def has_discount(self) -> bool:
        return self.discount_type != DiscountType.NONE and self.discount_value > 0


Index("uq_categories_name_lower", func.lower(Category.name), unique=True)
# a deleted food shouldn't block reusing its name
Index(
    "uq_foods_name_lower",
    func.lower(Food.name),
    unique=True,
    postgresql_where=Food.deleted_at.is_(None),
)
