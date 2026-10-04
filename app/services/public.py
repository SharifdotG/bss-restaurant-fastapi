from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Food
from app.schemas.public import Menu, MenuCategory, MenuFood, PublicRestaurant
from app.services.restaurant import get_restaurant


async def get_menu(session: AsyncSession) -> Menu:
    """The whole menu in one go, grouped by category. Sold out foods stay in so the
    frontend can show them greyed out, hidden categories and deleted foods don't."""
    restaurant = await get_restaurant(session)
    categories = await session.scalars(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.name)
    )
    foods = await session.scalars(
        select(Food).where(Food.deleted_at.is_(None)).order_by(Food.is_featured.desc(), Food.name)
    )

    by_category: dict[int | None, list[MenuFood]] = defaultdict(list)
    for food in foods:
        by_category[food.category_id].append(MenuFood.model_validate(food))

    return Menu(
        restaurant=PublicRestaurant.model_validate(restaurant),
        categories=[
            MenuCategory(
                id=category.id,
                name=category.name,
                description=category.description,
                image_key=category.image_key,
                foods=by_category[category.id],
            )
            for category in categories
            if by_category[category.id]
        ],
        uncategorized=by_category[None],
    )
