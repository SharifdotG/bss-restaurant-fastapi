from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RESTAURANT_ID, Restaurant
from app.schemas.restaurant import RestaurantUpdate

NULLABLE_FIELDS = {"address", "phone", "email", "tax_id", "receipt_footer"}


async def get_restaurant(session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, RESTAURANT_ID)
    if restaurant is None:
        # first use on a fresh database, start with the defaults
        await session.execute(insert(Restaurant).values(id=RESTAURANT_ID).on_conflict_do_nothing())
        restaurant = await session.get(Restaurant, RESTAURANT_ID)
    return restaurant


async def update_restaurant(session: AsyncSession, data: RestaurantUpdate) -> Restaurant:
    restaurant = await get_restaurant(session)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None or field in NULLABLE_FIELDS:
            setattr(restaurant, field, value)
    await session.commit()
    await session.refresh(restaurant)
    return restaurant
