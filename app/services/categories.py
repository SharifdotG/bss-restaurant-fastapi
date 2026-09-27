from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Category, Food
from app.schemas.menu import CategoryCreate, CategoryOut, CategoryUpdate
from app.services.common import commit_or_conflict
from app.services.images import ImageFolder, check_image_key, delete_image


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(Category.id).where(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    if await session.scalar(stmt):
        raise ConflictError(f"Category '{name}' already exists", code="category_exists")


def _food_count():
    return (
        select(func.count(Food.id))
        .where(Food.category_id == Category.id, Food.deleted_at.is_(None))
        .correlate(Category)
        .scalar_subquery()
    )


def _out(category: Category, food_count: int) -> CategoryOut:
    return CategoryOut.model_validate(category).model_copy(update={"food_count": food_count})


async def to_out(session: AsyncSession, category: Category) -> CategoryOut:
    count = await session.scalar(
        select(func.count(Food.id)).where(
            Food.category_id == category.id, Food.deleted_at.is_(None)
        )
    )
    return _out(category, count or 0)


async def list_categories(
    session: AsyncSession, include_inactive: bool = False
) -> list[CategoryOut]:
    stmt = select(Category, _food_count()).order_by(Category.sort_order, Category.name)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = await session.execute(stmt)
    return [_out(category, count) for category, count in rows]


async def get_category(session: AsyncSession, category_id: int) -> Category:
    category = await session.get(Category, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    return category


async def create_category(session: AsyncSession, data: CategoryCreate) -> Category:
    await _ensure_name_free(session, data.name)
    if data.image_key:
        check_image_key(data.image_key, ImageFolder.CATEGORIES)

    category = Category(**data.model_dump())
    session.add(category)
    await commit_or_conflict(session, "Category already exists", "category_exists")
    return category


async def update_category(
    session: AsyncSession, category: Category, data: CategoryUpdate
) -> Category:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        await _ensure_name_free(session, changes["name"], exclude_id=category.id)

    old_image = category.image_key
    if "image_key" in changes and changes["image_key"]:
        check_image_key(changes["image_key"], ImageFolder.CATEGORIES)

    for field, value in changes.items():
        if value is None and field not in ("description", "image_key"):
            continue
        setattr(category, field, value)

    await commit_or_conflict(session, "Category already exists", "category_exists")
    if old_image != category.image_key:
        await delete_image(old_image)
    return category


async def delete_category(session: AsyncSession, category: Category) -> None:
    if (await to_out(session, category)).food_count:
        raise ConflictError(
            "Move or delete the foods in this category first", code="category_not_empty"
        )
    await session.delete(category)
    await session.commit()
    await delete_image(category.image_key)
