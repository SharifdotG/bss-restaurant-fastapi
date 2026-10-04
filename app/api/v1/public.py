from fastapi import APIRouter, Depends, Response

from app.api.deps import SessionDep
from app.core.ratelimit import rate_limit
from app.models import Restaurant
from app.schemas.public import Menu, PublicRestaurant
from app.services import public as public_service
from app.services.restaurant import get_restaurant

# everything in here works without logging in, it's what customers see
router = APIRouter(
    prefix="/public",
    tags=["public"],
    dependencies=[Depends(rate_limit("public", limit=120, window=60))],
)

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
