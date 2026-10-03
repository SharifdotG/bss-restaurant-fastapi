from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import SessionDep, require_roles
from app.models import Order, User, UserRole
from app.schemas.order import OrderDetailOut, PaymentCreate
from app.services import payments as payment_service

router = APIRouter(prefix="/orders/{order_id}", tags=["payments"])

Cashier = Annotated[User, Depends(require_roles(UserRole.MANAGER, UserRole.CASHIER))]


@router.post("/payments", response_model=OrderDetailOut, status_code=status.HTTP_201_CREATED)
async def add_payment(
    order_id: int, body: PaymentCreate, session: SessionDep, actor: Cashier
) -> Order:
    """Takes money for an order, leave out `amount` to pay what's left.

    A split bill is just several payments. Once everything is paid a served order
    becomes paid by itself, an order paid before serving closes when it's served."""
    return await payment_service.record_payment(session, actor, order_id, body)
