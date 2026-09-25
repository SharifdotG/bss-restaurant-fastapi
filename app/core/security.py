import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

ALGORITHM = "HS256"

password_hasher = PasswordHash.recommended()
# verified against when the user doesn't exist so a login takes the same time either way
_DUMMY_HASH = password_hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash). new_hash is set when the stored hash uses old parameters."""
    return password_hasher.verify_and_update(password, password_hash)


def burn_password_check() -> None:
    password_hasher.verify("not-a-real-password", _DUMMY_HASH)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.InvalidTokenError (or a subclass) for anything that isn't a valid access token."""
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    # refresh tokens are long random strings, a plain sha256 is enough to store them
    return hashlib.sha256(token.encode()).hexdigest()
