from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, ManagerUser, SessionDep, require_roles
from app.models import Food, User, UserRole
from app.schemas.common import Page
from app.schemas.menu import FoodAvailability, FoodCreate, FoodListParams, FoodOut, FoodUpdate
from app.services import foods as food_service

router = APIRouter(prefix="/foods", tags=["menu"])

KitchenUser = Annotated[User, Depends(require_roles(UserRole.MANAGER, UserRole.CHEF))]


@router.get("", response_model=Page[FoodOut])
async def list_foods(
    session: SessionDep, _: CurrentUser, params: Annotated[FoodListParams, Query()]
) -> Page[FoodOut]:
    return await food_service.list_foods(session, params)


@router.post("", response_model=FoodOut, status_code=status.HTTP_201_CREATED)
async def create_food(body: FoodCreate, session: SessionDep, _: ManagerUser) -> Food:
    return await food_service.create_food(session, body)


@router.get("/{food_id}", response_model=FoodOut)
async def get_food(food_id: int, session: SessionDep, _: CurrentUser) -> Food:
    return await food_service.get_food(session, food_id)


@router.patch("/{food_id}", response_model=FoodOut)
async def update_food(food_id: int, body: FoodUpdate, session: SessionDep, _: ManagerUser) -> Food:
    food = await food_service.get_food(session, food_id)
    return await food_service.update_food(session, food, body)


@router.put("/{food_id}/availability", response_model=FoodOut)
async def set_availability(
    food_id: int, body: FoodAvailability, session: SessionDep, _: KitchenUser
) -> Food:
    """Quick sold out toggle, chefs can use this too."""
    food = await food_service.get_food(session, food_id)
    return await food_service.set_availability(session, food, body.is_available)


@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food(food_id: int, session: SessionDep, _: ManagerUser) -> Response:
    food = await food_service.get_food(session, food_id)
    await food_service.delete_food(session, food)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
