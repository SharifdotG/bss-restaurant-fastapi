import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import (
    burn_password_check,
    create_access_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)
from app.models import RefreshToken, User

logger = logging.getLogger(__name__)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _invalid_credentials() -> AuthenticationError:
    return AuthenticationError("Incorrect email or password", code="invalid_credentials")


def _invalid_refresh() -> AuthenticationError:
    return AuthenticationError("Refresh token is invalid or expired", code="invalid_refresh_token")


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None:
        burn_password_check()
        raise _invalid_credentials()

    valid, new_hash = verify_password(password, user.password_hash)
    if not valid:
        raise _invalid_credentials()
    if not user.is_active:
        raise PermissionDeniedError("This account has been deactivated", code="account_disabled")

    if new_hash:
        user.password_hash = new_hash
    return user


def issue_tokens(
    session: AsyncSession,
    user: User,
    user_agent: str | None,
    family_id: uuid.UUID | None = None,
) -> TokenPair:
    raw_refresh = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
            user_agent=user_agent[:255] if user_agent else None,
        )
    )
    access, expires_in = create_access_token(user.id, user.role)
    return TokenPair(access_token=access, refresh_token=raw_refresh, expires_in=expires_in)


async def login(
    session: AsyncSession, email: str, password: str, user_agent: str | None
) -> tuple[User, TokenPair]:
    user = await authenticate(session, email, password)
    user.last_login_at = datetime.now(UTC)
    tokens = issue_tokens(session, user, user_agent)
    await session.commit()
    return user, tokens


async def refresh(
    session: AsyncSession, raw_token: str, user_agent: str | None
) -> tuple[User, TokenPair]:
    token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    if token is None:
        raise _invalid_refresh()

    now = datetime.now(UTC)
    if token.revoked_at is not None:
        # an already rotated token came back, someone else has a copy of it
        logger.warning("refresh token reuse detected for user %s, revoking session", token.user_id)
        await _revoke(session, RefreshToken.family_id == token.family_id)
        await session.commit()
        raise _invalid_refresh()

    if token.expires_at <= now:
        raise _invalid_refresh()

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise _invalid_refresh()

    token.revoked_at = now
    tokens = issue_tokens(session, user, user_agent, family_id=token.family_id)
    await session.commit()
    return user, tokens


async def logout(session: AsyncSession, raw_token: str) -> None:
    """Ends the session the refresh token belongs to. Unknown tokens are ignored."""
    family_id = await session.scalar(
        select(RefreshToken.family_id).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if family_id is not None:
        await _revoke(session, RefreshToken.family_id == family_id)
        await session.commit()


async def revoke_all_sessions(session: AsyncSession, user_id: int) -> None:
    """Caller is responsible for committing."""
    await _revoke(session, RefreshToken.user_id == user_id)


async def _revoke(session: AsyncSession, condition) -> None:
    await session.execute(
        update(RefreshToken)
        .where(condition, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
