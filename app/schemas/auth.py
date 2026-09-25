from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import CamelModel
from app.schemas.user import UserOut


class LoginIn(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(CamelModel):
    refresh_token: str = Field(min_length=1, max_length=255)


class TokenOut(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: UserOut


class OAuth2TokenOut(BaseModel):
    # plain snake_case on purpose, swagger's authorize dialog expects exactly this
    access_token: str
    token_type: str = "bearer"
