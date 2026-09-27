from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, computed_field
from pydantic.alias_generators import to_camel

from app.storage import file_url


class CamelModel(BaseModel):
    """Base for every request/response schema: camelCase over the wire, snake_case in python.

    FastAPI dumps responses by alias already. model_dump() stays snake_case on purpose so
    it can be fed straight into the ORM models.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )


# Decimal would be sent as a string by default, frontends want a number
Money = Annotated[
    Decimal,
    Field(max_digits=12, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]


class ListParams(CamelModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    search: str | None = Field(None, max_length=100)
    sort: str | None = Field(None, description="Comma separated fields, prefix with - for desc")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page[T](CamelModel):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class Message(CamelModel):
    message: str


class WithImage(CamelModel):
    """Response mixin: keeps the storage key internal and exposes a ready to use url."""

    image_key: str | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def image_url(self) -> str | None:
        return file_url(self.image_key)
