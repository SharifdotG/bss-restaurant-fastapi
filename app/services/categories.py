from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Category
from app.schemas.menu import CategoryCreate, CategoryUpdate
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


async def list_categories(session: AsyncSession, include_inactive: bool = False) -> list[Category]:
    stmt = select(Category).order_by(Category.sort_order, Category.name)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    return list(await session.scalars(stmt))


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
    await session.delete(category)
    await session.commit()
    await delete_image(category.image_key)
