from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.schemas.common import CamelModel, WithImage

CategoryName = Annotated[str, Field(min_length=1, max_length=100)]


class CategoryCreate(CamelModel):
    name: CategoryName
    description: str | None = Field(None, max_length=500)
    image_key: str | None = None
    sort_order: int = Field(0, ge=0, le=10_000)
    is_active: bool = True


class CategoryUpdate(CamelModel):
    name: CategoryName | None = None
    description: str | None = Field(None, max_length=500)
    image_key: str | None = None
    sort_order: int | None = Field(None, ge=0, le=10_000)
    is_active: bool | None = None


class CategoryOut(WithImage):
    id: int
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
