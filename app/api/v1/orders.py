from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.models import Order, User, UserRole
from app.schemas.common import Page
from app.schemas.order import OrderCreate, OrderListParams, OrderOut
from app.services import orders as order_service

router = APIRouter(prefix="/orders", tags=["orders"])

# people who take orders from customers
FrontOfHouse = Annotated[
    User, Depends(require_roles(UserRole.MANAGER, UserRole.WAITER, UserRole.CASHIER))
]


@router.get("", response_model=Page[OrderOut])
async def list_orders(
    session: SessionDep, _: CurrentUser, params: Annotated[OrderListParams, Query()]
) -> Page[OrderOut]:
    return await order_service.list_orders(session, params)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderCreate, session: SessionDep, actor: FrontOfHouse) -> Order:
    return await order_service.create_order(session, actor, body)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, session: SessionDep, _: CurrentUser) -> Order:
    return await order_service.get_order(session, order_id)
