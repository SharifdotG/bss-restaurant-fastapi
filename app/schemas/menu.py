from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator

from app.models.menu import DiscountType
from app.schemas.common import CamelModel, ListParams, Money, WithImage

CategoryName = Annotated[str, Field(min_length=1, max_length=100)]


class CategoryCreate(CamelModel):
    name: CategoryName
    description: str | None = Field(None, max_length=500)
    image_key: str | None = None
    sort_order: int = Field(0, ge=0, le=10_000)
    is_active: bool = True


class CategoryUpdate(CamelModel):
    name: CategoryName | None = None
    description: str | None = Field(None, max_length=500)
    image_key: str | None = None
    sort_order: int | None = Field(None, ge=0, le=10_000)
    is_active: bool | None = None


class CategoryOut(WithImage):
    id: int
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    food_count: int = 0
    created_at: datetime
    updated_at: datetime


PositiveMoney = Annotated[Money, Field(ge=0)]
FoodName = Annotated[str, Field(min_length=1, max_length=200)]


def discount_error(price: Decimal, discount_type: DiscountType, value: Decimal) -> str | None:
    if discount_type == DiscountType.PERCENTAGE and value > 100:
        return "A percentage discount can't be more than 100"
    if discount_type == DiscountType.FLAT and value > price:
        return "A flat discount can't be more than the price"
    return None


class FoodCreate(CamelModel):
    name: FoodName
    description: str | None = Field(None, max_length=2000)
    category_id: int | None = None
    price: PositiveMoney
    discount_type: DiscountType = DiscountType.NONE
    discount_value: PositiveMoney = Decimal(0)
    is_available: bool = True
    is_featured: bool = False
    preparation_minutes: int | None = Field(None, ge=1, le=300)
    image_key: str | None = None

    @model_validator(mode="after")
    def _check_discount(self) -> Self:
        if error := discount_error(self.price, self.discount_type, self.discount_value):
            raise ValueError(error)
        return self


class FoodUpdate(CamelModel):
    name: FoodName | None = None
    description: str | None = Field(None, max_length=2000)
    category_id: int | None = None
    price: PositiveMoney | None = None
    discount_type: DiscountType | None = None
    discount_value: PositiveMoney | None = None
    is_available: bool | None = None
    is_featured: bool | None = None
    preparation_minutes: int | None = Field(None, ge=1, le=300)
    image_key: str | None = None


class FoodAvailability(CamelModel):
    is_available: bool


class FoodCategory(CamelModel):
    id: int
    name: str


class FoodOut(WithImage):
    id: int
    name: str
    description: str | None
    price: Money
    discount_type: DiscountType
    discount_value: Money
    final_price: Money
    has_discount: bool
    category: FoodCategory | None
    is_available: bool
    is_featured: bool
    preparation_minutes: int | None
    created_at: datetime
    updated_at: datetime


class FoodListParams(ListParams):
    category_id: int | None = None
    is_available: bool | None = None
    is_featured: bool | None = None
