from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas.user import ProfileUpdate
from app.services import auth as auth_service


async def ensure_unique(
    session: AsyncSession,
    *,
    email: str | None = None,
    phone: str | None = None,
    exclude_id: int | None = None,
) -> None:
    if email is not None:
        stmt = select(User.id).where(func.lower(User.email) == email.lower())
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if await session.scalar(stmt):
            raise ConflictError("A user with this email already exists", code="email_taken")

    if phone is not None:
        stmt = select(User.id).where(User.phone == phone)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if await session.scalar(stmt):
            raise ConflictError("A user with this phone number already exists", code="phone_taken")


async def commit_or_conflict(session: AsyncSession) -> None:
    # the checks above can still lose a race with another request
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("A user with this email or phone number already exists") from None


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate) -> User:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("phone"):
        await ensure_unique(session, phone=changes["phone"], exclude_id=user.id)
    for field, value in changes.items():
        if field in ("first_name", "last_name") and value is None:
            continue
        setattr(user, field, value)
    await commit_or_conflict(session)
    return user


async def change_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    user_agent: str | None,
) -> auth_service.TokenPair:
    valid, _ = verify_password(current_password, user.password_hash)
    if not valid:
        raise BadRequestError("Current password is incorrect", code="wrong_password")

    user.password_hash = hash_password(new_password)
    # log out every other device, this one gets a fresh pair
    await auth_service.revoke_all_sessions(session, user.id)
    tokens = auth_service.issue_tokens(session, user, user_agent)
    await session.commit()
    return tokens
