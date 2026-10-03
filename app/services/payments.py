from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import Order, OrderStatus, Payment, PaymentKind, User
from app.schemas.order import PaymentCreate
from app.services.orders import close_as_paid, get_order


async def _lock(session: AsyncSession, order_id: int) -> Order:
    # one cashier at a time, two payments landing together could overpay the bill
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def record_payment(
    session: AsyncSession, actor: User, order_id: int, data: PaymentCreate
) -> Order:
    order = await _lock(session, order_id)
    if order.is_closed:
        raise ConflictError(f"The order is already {order.status}", code="order_closed")

    due = order.balance_due
    if due <= 0:
        raise ConflictError("Nothing left to pay on this order", code="nothing_to_pay")

    amount = data.amount
    if amount is None:
        # cash without an amount pays as much as was handed over
        amount = min(data.tendered, due) if data.tendered else due
    if amount > due:
        raise ConflictError(
            f"Only {due} is left to pay", code="overpayment", extra={"balanceDue": float(due)}
        )
    if data.tendered is not None and data.tendered < amount:
        raise BadRequestError("Cash given is less than the amount", code="not_enough_cash")

    session.add(
        Payment(
            order_id=order.id,
            kind=PaymentKind.PAYMENT,
            method=data.method,
            amount=amount,
            tendered=data.tendered,
            reference=data.reference.strip() if data.reference else None,
            note=data.note,
            received_by_id=actor.id,
        )
    )
    order.amount_paid += amount
    if order.status == OrderStatus.SERVED and order.amount_paid >= order.total:
        close_as_paid(session, order, actor, "bill settled")

    await session.commit()
    return await get_order(session, order.id)
