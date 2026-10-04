from app.models.menu import DiscountType
from app.schemas.common import CamelModel, Money, WithImage
from app.schemas.restaurant import Percent


class PublicRestaurant(CamelModel):
    name: str
    address: str | None
    phone: str | None
    email: str | None
    currency: str
    currency_symbol: str
    vat_percent: Percent
    service_charge_percent: Percent


class MenuFood(WithImage):
    id: int
    name: str
    description: str | None
    price: Money
    discount_type: DiscountType
    discount_value: Money
    final_price: Money
    has_discount: bool
    is_available: bool
    is_featured: bool
    preparation_minutes: int | None


class MenuCategory(WithImage):
    id: int
    name: str
    description: str | None
    foods: list[MenuFood]


class Menu(CamelModel):
    restaurant: PublicRestaurant
    categories: list[MenuCategory]
    uncategorized: list[MenuFood]
