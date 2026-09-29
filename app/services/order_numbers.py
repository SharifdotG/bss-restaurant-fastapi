from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import business_date
from app.models import OrderCounter


async def next_order_number(session: AsyncSession, day: date | None = None) -> str:
    """Next number for the day, like 260930-0042.

    The upsert locks the day's counter row until the transaction ends, so two waiters
    placing orders at the same moment can never get the same number. If the order
    insert fails the counter rolls back with it.
    """
    day = day or business_date()
    stmt = (
        insert(OrderCounter)
        .values(business_date=day, last_number=1)
        .on_conflict_do_update(
            index_elements=[OrderCounter.business_date],
            set_={"last_number": OrderCounter.last_number + 1},
        )
        .returning(OrderCounter.last_number)
    )
    number = await session.scalar(stmt)
    return f"{day:%y%m%d}-{number:04d}"
