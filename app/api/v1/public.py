from fastapi import APIRouter, Depends, Response, status

from app.api.deps import SessionDep
from app.core.ratelimit import rate_limit
from app.models import DiningTable, Order, Restaurant
from app.schemas.public import (
    Menu,
    OnlineOrderCreate,
    PublicOrder,
    PublicOrderCreate,
    PublicRestaurant,
    PublicTable,
)
from app.services import public as public_service
from app.services.restaurant import get_restaurant

# everything in here works without logging in, it's what customers see
router = APIRouter(
    prefix="/public",
    tags=["public"],
    dependencies=[Depends(rate_limit("public", limit=120, window=60))],
)

# placing orders is limited much harder than reading the menu
OrderLimit = Depends(rate_limit("public-orders", limit=10, window=600))

# the menu doesn't change every second, let browsers and cdns keep it for a bit
CACHE_FOR_A_MINUTE = "public, max-age=60"


@router.get("/restaurant", response_model=PublicRestaurant)
async def restaurant(session: SessionDep, response: Response) -> Restaurant:
    response.headers["Cache-Control"] = CACHE_FOR_A_MINUTE
    return await get_restaurant(session)


@router.get("/menu", response_model=Menu)
async def menu(session: SessionDep, response: Response) -> Menu:
    """Restaurant details plus every visible category with its foods."""
    response.headers["Cache-Control"] = CACHE_FOR_A_MINUTE
    return await public_service.get_menu(session)


@router.get("/tables/{qr_token}", response_model=PublicTable)
async def table(qr_token: str, session: SessionDep) -> DiningTable:
    """The table behind a QR code, so the page can say "Table 4"."""
    return await public_service.get_table(session, qr_token)


@router.post(
    "/tables/{qr_token}/orders",
    response_model=PublicOrder,
    status_code=status.HTTP_201_CREATED,
    dependencies=[OrderLimit],
)
async def order_from_table(qr_token: str, body: PublicOrderCreate, session: SessionDep) -> Order:
    """Orders from the QR code on the table. The order waits as pending until a waiter
    confirms it, keep the `trackingCode` to follow it."""
    return await public_service.place_table_order(session, qr_token, body)


@router.post(
    "/orders",
    response_model=PublicOrder,
    status_code=status.HTTP_201_CREATED,
    dependencies=[OrderLimit],
)
async def order_online(body: OnlineOrderCreate, session: SessionDep) -> Order:
    """Takeaway from the website, only when the restaurant has online orders switched on."""
    return await public_service.place_online_order(session, body)


@router.get("/orders/{tracking_code}", response_model=PublicOrder)
async def track_order(tracking_code: str, session: SessionDep) -> Order:
    """Status, items and bill of an order. Works for any order, staff can hand out the code."""
    return await public_service.get_public_order(session, tracking_code)


@router.post(
    "/orders/{tracking_code}/cancel", response_model=PublicOrder, dependencies=[OrderLimit]
)
async def cancel_order(tracking_code: str, session: SessionDep) -> Order:
    """Only while the order is still pending and nothing was paid, see `canCancel`."""
    return await public_service.cancel_public_order(session, tracking_code)
