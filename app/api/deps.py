from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.models import User, UserRole

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error is off so a missing token goes through our own error format
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/token", auto_error=False)


async def authenticate_token(session: AsyncSession, token: str) -> tuple[User, dict[str, Any]]:
    """The active user behind an access token, along with the token's claims."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        # the frontend looks for this code to know it should refresh
        raise AuthenticationError("Access token has expired", code="token_expired") from None
    except (jwt.InvalidTokenError, ValueError):
        raise AuthenticationError("Invalid access token", code="invalid_token") from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid access token", code="invalid_token")
    return user, payload


async def get_current_user(
    session: SessionDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    user, _ = await authenticate_token(session, token)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Admins can always pass, everyone else needs one of the given roles."""

    async def checker(user: CurrentUser) -> User:
        if user.role != UserRole.ADMIN and user.role not in roles:
            raise PermissionDeniedError()
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles())]
ManagerUser = Annotated[User, Depends(require_roles(UserRole.MANAGER))]
