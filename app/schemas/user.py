import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import CamelModel, ListParams


def _check_password(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("password must contain at least one letter and one number")
    return value


Password = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_check_password)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Phone = Annotated[str, Field(pattern=r"^\+?[0-9][0-9 -]{5,18}$")]


class UserOut(CamelModel):
    id: int
    email: str
    first_name: str
    last_name: str
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(CamelModel):
    email: EmailStr
    password: Password
    first_name: Name
    last_name: Name
    phone: Phone | None = None
    role: UserRole = UserRole.WAITER


class UserUpdate(CamelModel):
    first_name: Name | None = None
    last_name: Name | None = None
    phone: Phone | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserListParams(ListParams):
    role: UserRole | None = None
    is_active: bool | None = None


class ProfileUpdate(CamelModel):
    first_name: Name | None = None
    last_name: Name | None = None
    phone: Phone | None = None


class PasswordChange(CamelModel):
    current_password: str = Field(max_length=128)
    new_password: Password


class PasswordReset(CamelModel):
    new_password: Password
