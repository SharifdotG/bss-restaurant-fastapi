from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.core.security import hash_password
from app.models import Employee, User
from app.schemas.common import Page
from app.schemas.employee import (
    EmployeeAccountIn,
    EmployeeCreate,
    EmployeeListParams,
    EmployeeOut,
    EmployeeUpdate,
)
from app.services import users as user_service
from app.services.common import commit_or_conflict
from app.services.images import ImageFolder, check_image_key, delete_image

EMPLOYEE_SORTS = {
    "firstName": Employee.first_name,
    "lastName": Employee.last_name,
    "designation": Employee.designation,
    "joinDate": Employee.join_date,
    "createdAt": Employee.created_at,
}
REQUIRED_FIELDS = {"first_name", "last_name", "designation", "join_date"}
# these are copied to the login account so both stay in sync
SHARED_WITH_USER = {"first_name", "last_name", "phone"}

DUPLICATE_MESSAGE = "An employee with this phone or NID already exists"


def _with_user():
    return select(Employee).options(selectinload(Employee.user))


async def _ensure_unique(
    session: AsyncSession,
    *,
    phone: str | None = None,
    nid: str | None = None,
    exclude_id: int | None = None,
) -> None:
    for column, value, label in (
        (Employee.phone, phone, "phone number"),
        (Employee.nid, nid, "NID"),
    ):
        if value is None:
            continue
        stmt = select(Employee.id).where(column == value)
        if exclude_id is not None:
            stmt = stmt.where(Employee.id != exclude_id)
        if await session.scalar(stmt):
            raise ConflictError(f"Another employee has this {label}", code="employee_exists")


async def list_employees(session: AsyncSession, params: EmployeeListParams) -> Page[EmployeeOut]:
    stmt = _with_user()
    if params.is_active is not None:
        stmt = stmt.where(Employee.is_active.is_(params.is_active))
    if params.designation:
        stmt = stmt.where(func.lower(Employee.designation) == params.designation.lower())
    if params.has_account is not None:
        has = Employee.user_id.is_not(None)
        stmt = stmt.where(has if params.has_account else ~has)
    term = search_filter(
        params.search,
        Employee.first_name,
        Employee.last_name,
        Employee.email,
        Employee.phone,
        Employee.designation,
    )
    if term is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(
        stmt, params.sort, EMPLOYEE_SORTS, default="firstName", tiebreaker=Employee.id
    )
    return await paginate(session, stmt, params, EmployeeOut)


async def get_employee(session: AsyncSession, employee_id: int) -> Employee:
    employee = await session.scalar(_with_user().where(Employee.id == employee_id))
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee


def _new_account(employee: Employee, account: EmployeeAccountIn) -> User:
    return User(
        email=employee.email.lower(),
        password_hash=hash_password(account.password),
        first_name=employee.first_name,
        last_name=employee.last_name,
        phone=employee.phone,
        role=account.role,
    )


async def _check_account_allowed(
    session: AsyncSession, actor: User, employee: Employee, account: EmployeeAccountIn
) -> None:
    user_service.check_can_manage(actor, account.role)
    await user_service.ensure_unique(session, email=employee.email, phone=employee.phone)


async def create_employee(session: AsyncSession, actor: User, data: EmployeeCreate) -> Employee:
    await _ensure_unique(session, phone=data.phone, nid=data.nid)
    if data.image_key:
        check_image_key(data.image_key, ImageFolder.USERS)

    employee = Employee(**data.model_dump(exclude={"account"}))
    if data.account:
        await _check_account_allowed(session, actor, employee, data.account)
        employee.user = _new_account(employee, data.account)

    # employee and account go in one transaction, no half created staff
    session.add(employee)
    await commit_or_conflict(session, DUPLICATE_MESSAGE, "employee_exists")
    return await get_employee(session, employee.id)


async def create_account(
    session: AsyncSession, actor: User, employee: Employee, data: EmployeeAccountIn
) -> Employee:
    if employee.user_id is not None:
        raise ConflictError("This employee already has an account", code="account_exists")
    if not employee.email:
        raise BadRequestError("Add an email to the employee first", code="email_required")
    if not employee.is_active:
        raise BadRequestError("The employee is not active", code="employee_inactive")

    await _check_account_allowed(session, actor, employee, data)
    employee.user = _new_account(employee, data)
    await commit_or_conflict(session, "A user with this email or phone already exists")
    return await get_employee(session, employee.id)


async def update_employee(
    session: AsyncSession, actor: User, employee: Employee, data: EmployeeUpdate
) -> Employee:
    changes = {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if value is not None or field not in REQUIRED_FIELDS
    }
    await _ensure_unique(
        session, phone=changes.get("phone"), nid=changes.get("nid"), exclude_id=employee.id
    )
    if changes.get("image_key"):
        check_image_key(changes["image_key"], ImageFolder.USERS)
    if (
        employee.date_of_birth
        and changes.get("join_date")
        and changes["join_date"] <= employee.date_of_birth
    ):
        raise BadRequestError("Join date must be after the date of birth")

    user = employee.user
    if user is not None and SHARED_WITH_USER & changes.keys():
        user_service.check_can_manage(actor, user.role)
        if changes.get("phone"):
            await user_service.ensure_unique(session, phone=changes["phone"], exclude_id=user.id)
        for field in SHARED_WITH_USER & changes.keys():
            setattr(user, field, changes[field])

    old_image = employee.image_key
    for field, value in changes.items():
        setattr(employee, field, value)
    await commit_or_conflict(session, DUPLICATE_MESSAGE, "employee_exists")

    if old_image and old_image != employee.image_key:
        await delete_image(old_image)
    return employee


async def deactivate_employee(session: AsyncSession, actor: User, employee: Employee) -> None:
    """Employees are never deleted, their orders and history stay intact."""
    employee.is_active = False
    user = employee.user
    if user is not None and user.is_active:
        # also commits the employee change
        await user_service.deactivate_user(session, actor, user)
    else:
        await session.commit()
