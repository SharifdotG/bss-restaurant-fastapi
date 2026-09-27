from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.models import Category, Food
from app.schemas.common import Page
from app.schemas.menu import (
    FoodCreate,
    FoodListParams,
    FoodOut,
    FoodUpdate,
    discount_error,
)
from app.services.common import commit_or_conflict
from app.services.images import ImageFolder, check_image_key, delete_image

FOOD_SORTS = {
    "name": Food.name,
    "price": Food.price,
    "finalPrice": Food.final_price,
    "createdAt": Food.created_at,
    "updatedAt": Food.updated_at,
}

# fields that can be set back to null with an explicit null in a PATCH
NULLABLE_FIELDS = {"description", "category_id", "preparation_minutes", "image_key"}


def _active_foods():
    return select(Food).where(Food.deleted_at.is_(None)).options(selectinload(Food.category))


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(Food.id).where(func.lower(Food.name) == name.lower(), Food.deleted_at.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(Food.id != exclude_id)
    if await session.scalar(stmt):
        raise ConflictError(f"A food named '{name}' already exists", code="food_exists")


async def _ensure_category_exists(session: AsyncSession, category_id: int | None) -> None:
    if category_id is not None and await session.get(Category, category_id) is None:
        raise BadRequestError("Category does not exist", code="invalid_category")


async def list_foods(session: AsyncSession, params: FoodListParams) -> Page[FoodOut]:
    stmt = _active_foods()
    if params.category_id is not None:
        stmt = stmt.where(Food.category_id == params.category_id)
    if params.is_available is not None:
        stmt = stmt.where(Food.is_available.is_(params.is_available))
    if params.is_featured is not None:
        stmt = stmt.where(Food.is_featured.is_(params.is_featured))
    if (term := search_filter(params.search, Food.name, Food.description)) is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(stmt, params.sort, FOOD_SORTS, default="name", tiebreaker=Food.id)
    return await paginate(session, stmt, params, FoodOut)


async def get_food(session: AsyncSession, food_id: int) -> Food:
    food = await session.scalar(_active_foods().where(Food.id == food_id))
    if food is None:
        raise NotFoundError("Food not found")
    return food


async def create_food(session: AsyncSession, data: FoodCreate) -> Food:
    await _ensure_name_free(session, data.name)
    await _ensure_category_exists(session, data.category_id)
    if data.image_key:
        check_image_key(data.image_key, ImageFolder.FOODS)

    food = Food(**data.model_dump())
    session.add(food)
    await commit_or_conflict(session, "A food with this name already exists", "food_exists")
    await session.refresh(food, ["category"])
    return food


async def update_food(session: AsyncSession, food: Food, data: FoodUpdate) -> Food:
    changes = {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if value is not None or field in NULLABLE_FIELDS
    }
    if "name" in changes:
        await _ensure_name_free(session, changes["name"], exclude_id=food.id)
    if "category_id" in changes:
        await _ensure_category_exists(session, changes["category_id"])
    if changes.get("image_key"):
        check_image_key(changes["image_key"], ImageFolder.FOODS)

    # the discount rules depend on the price, so check them against the final state
    error = discount_error(
        changes.get("price", food.price),
        changes.get("discount_type", food.discount_type),
        changes.get("discount_value", food.discount_value),
    )
    if error:
        raise BadRequestError(error, code="invalid_discount")

    old_image = food.image_key
    for field, value in changes.items():
        setattr(food, field, value)
    await commit_or_conflict(session, "A food with this name already exists", "food_exists")

    if old_image and old_image != food.image_key:
        await delete_image(old_image)
    # category_id may have changed, the loaded relationship would be stale
    await session.refresh(food, ["category"])
    return food


async def set_availability(session: AsyncSession, food: Food, is_available: bool) -> Food:
    food.is_available = is_available
    await session.commit()
    return food


async def delete_food(session: AsyncSession, food: Food) -> None:
    food.deleted_at = datetime.now(UTC)
    food.is_available = False
    await session.commit()
