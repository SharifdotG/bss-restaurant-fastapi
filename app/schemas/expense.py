from datetime import date, datetime
from typing import Annotated, Self

from pydantic import Field, computed_field, model_validator

from app.core.timeutils import business_date
from app.models.expense import ExpenseCategory
from app.schemas.common import CamelModel, ListParams, Money
from app.schemas.order import PersonRef
from app.storage import file_url

Amount = Annotated[Money, Field(gt=0)]
Title = Annotated[str, Field(min_length=1, max_length=200)]


def _check_date(value: date | None) -> None:
    if value and value > business_date():
        raise ValueError("expense date can't be in the future")


class ExpenseCreate(CamelModel):
    title: Title
    category: ExpenseCategory
    amount: Amount
    expense_date: date = Field(default_factory=business_date)
    paid_to: str | None = Field(None, max_length=150)
    notes: str | None = Field(None, max_length=2000)
    receipt_key: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _check_date(self.expense_date)
        return self


class ExpenseUpdate(CamelModel):
    title: Title | None = None
    category: ExpenseCategory | None = None
    amount: Amount | None = None
    expense_date: date | None = None
    paid_to: str | None = Field(None, max_length=150)
    notes: str | None = Field(None, max_length=2000)
    receipt_key: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _check_date(self.expense_date)
        return self


class ExpenseOut(CamelModel):
    id: int
    title: str
    category: ExpenseCategory
    amount: Money
    expense_date: date
    paid_to: str | None
    notes: str | None
    receipt_key: str | None = Field(default=None, exclude=True)
    created_by: PersonRef | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def receipt_url(self) -> str | None:
        return file_url(self.receipt_key)


class ExpenseListParams(ListParams):
    category: list[ExpenseCategory] | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_amount: Money | None = None
    max_amount: Money | None = None
