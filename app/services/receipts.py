from datetime import datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.timeutils import local_now, restaurant_tz
from app.models import OrderStatus, PaymentMethod
from app.services.orders import get_order
from app.services.restaurant import get_restaurant

templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "templates"),
    # food and customer names end up in the html
    autoescape=select_autoescape(),
)

METHOD_LABELS = {
    PaymentMethod.CASH: "Cash",
    PaymentMethod.CARD: "Card",
    PaymentMethod.MOBILE: "Mobile banking",
}


def percent(rate: Decimal) -> str:
    return f"{rate.normalize():f}%"


async def render_receipt(session: AsyncSession, order_id: int, auto_print: bool = False) -> str:
    """A bill while the order is open, a receipt once it's paid."""
    order = await get_order(session, order_id)
    if order.status == OrderStatus.CANCELLED:
        raise ConflictError("Cancelled orders don't have a bill", code="order_cancelled")
    restaurant = await get_restaurant(session)
    tz = restaurant_tz()

    def money(value: Decimal) -> str:
        return f"{restaurant.currency_symbol}{value:,.2f}"

    def local(moment: datetime) -> datetime:
        return moment.astimezone(tz)

    return templates.get_template("receipt.html").render(
        title="Receipt" if order.status == OrderStatus.PAID else "Bill",
        order=order,
        restaurant=restaurant,
        methods=METHOD_LABELS,
        money=money,
        percent=percent,
        local=local,
        printed_at=local_now(),
        auto_print=auto_print,
    )
