from datetime import date, datetime
from typing import Annotated, Self

from pydantic import EmailStr, Field, model_validator

from app.models.employee import Gender
from app.models.user import UserRole
from app.schemas.common import CamelModel, ListParams, Money, WithImage
from app.schemas.table import TableRef
from app.schemas.user import Name, Password, Phone

OptionalName = Annotated[str, Field(max_length=100)] | None


def _check_dates(join_date: date | None, date_of_birth: date | None) -> None:
    today = date.today()
    if date_of_birth and date_of_birth >= today:
        raise ValueError("date of birth must be in the past")
    if join_date and date_of_birth and join_date <= date_of_birth:
        raise ValueError("join date must be after the date of birth")


class EmployeeAccountIn(CamelModel):
    """Creates a login for the employee, uses the employee's email."""

    role: UserRole = UserRole.WAITER
    password: Password


class EmployeeCreate(CamelModel):
    first_name: Name
    last_name: Name
    email: EmailStr | None = None
    phone: Phone | None = None
    designation: Annotated[str, Field(min_length=1, max_length=100)]
    join_date: date
    date_of_birth: date | None = None
    gender: Gender | None = None
    nid: Annotated[str, Field(min_length=5, max_length=30)] | None = None
    address: Annotated[str, Field(max_length=255)] | None = None
    father_name: OptionalName = None
    mother_name: OptionalName = None
    spouse_name: OptionalName = None
    monthly_salary: Annotated[Money, Field(ge=0)] | None = None
    image_key: str | None = None
    account: EmployeeAccountIn | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _check_dates(self.join_date, self.date_of_birth)
        if self.account and not self.email:
            raise ValueError("an email is needed to create a login account")
        return self


class EmployeeUpdate(CamelModel):
    first_name: Name | None = None
    last_name: Name | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    designation: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    join_date: date | None = None
    date_of_birth: date | None = None
    gender: Gender | None = None
    nid: Annotated[str, Field(min_length=5, max_length=30)] | None = None
    address: Annotated[str, Field(max_length=255)] | None = None
    father_name: OptionalName = None
    mother_name: OptionalName = None
    spouse_name: OptionalName = None
    monthly_salary: Annotated[Money, Field(ge=0)] | None = None
    image_key: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _check_dates(self.join_date, self.date_of_birth)
        return self


class EmployeeAccountOut(CamelModel):
    id: int
    email: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None


class EmployeeOut(WithImage):
    id: int
    first_name: str
    last_name: str
    full_name: str
    email: str | None
    phone: str | None
    designation: str
    join_date: date
    date_of_birth: date | None
    gender: Gender | None
    nid: str | None
    address: str | None
    father_name: str | None
    mother_name: str | None
    spouse_name: str | None
    monthly_salary: Money | None
    is_active: bool
    account: EmployeeAccountOut | None = Field(None, validation_alias="user")
    tables: list[TableRef]
    created_at: datetime
    updated_at: datetime


class EmployeeListParams(ListParams):
    is_active: bool | None = None
    designation: str | None = Field(None, max_length=100)
    has_account: bool | None = None
