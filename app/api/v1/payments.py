from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import HTMLResponse

from app.api.deps import CurrentUser, ManagerUser, SessionDep, require_roles
from app.models import Order, User, UserRole
from app.schemas.order import OrderDetailOut, PaymentCreate, RefundCreate
from app.services import payments as payment_service
from app.services import receipts as receipt_service

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


@router.post("/refunds", response_model=OrderDetailOut, status_code=status.HTTP_201_CREATED)
async def add_refund(
    order_id: int, body: RefundCreate, session: SessionDep, actor: ManagerUser
) -> Order:
    """Gives money back, at most what was paid. Managers only.

    Also needed before cancelling an order that was already (partly) paid."""
    return await payment_service.record_refund(session, actor, order_id, body)


@router.get("/receipt", response_class=HTMLResponse)
async def receipt(
    order_id: int,
    session: SessionDep,
    _: CurrentUser,
    auto_print: Annotated[bool, Query(alias="print")] = False,
) -> HTMLResponse:
    """Printable bill (open orders) or receipt (paid orders) as html, sized for 80mm printers.
    `print=true` opens the print dialog as soon as it loads."""
    html = await receipt_service.render_receipt(session, order_id, auto_print=auto_print)
    return HTMLResponse(html)
