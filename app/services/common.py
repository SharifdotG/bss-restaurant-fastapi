from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError


async def commit_or_conflict(
    session: AsyncSession,
    message: str = "This conflicts with existing data",
    code: str = "conflict",
) -> None:
    """Commit, turning a unique violation into a 409.

    The explicit "already exists" checks in the services give nicer messages, this
    only covers the case where two requests race each other.
    """
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(message, code=code) from None
