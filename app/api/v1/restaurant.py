from fastapi import APIRouter

from app.api.deps import CurrentUser, ManagerUser, SessionDep
from app.models import Restaurant
from app.schemas.restaurant import RestaurantOut, RestaurantUpdate
from app.services import restaurant as restaurant_service

router = APIRouter(prefix="/restaurant", tags=["restaurant"])


@router.get("", response_model=RestaurantOut)
async def get_restaurant(session: SessionDep, _: CurrentUser) -> Restaurant:
    return await restaurant_service.get_restaurant(session)


@router.patch("", response_model=RestaurantOut)
async def update_restaurant(
    body: RestaurantUpdate, session: SessionDep, _: ManagerUser
) -> Restaurant:
    """Name and contact details for receipts, currency, VAT and service charge.
    New rates apply to orders placed after the change."""
    return await restaurant_service.update_restaurant(session, body)
