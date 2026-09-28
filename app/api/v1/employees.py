from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ManagerUser, SessionDep
from app.models import Employee
from app.schemas.common import Page
from app.schemas.employee import (
    EmployeeAccountIn,
    EmployeeCreate,
    EmployeeListParams,
    EmployeeOut,
    EmployeeUpdate,
)
from app.services import employees as employee_service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=Page[EmployeeOut])
async def list_employees(
    session: SessionDep, _: ManagerUser, params: Annotated[EmployeeListParams, Query()]
) -> Page[EmployeeOut]:
    return await employee_service.list_employees(session, params)


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate, session: SessionDep, actor: ManagerUser
) -> Employee:
    """Pass `account` to create a login for the employee in the same request."""
    return await employee_service.create_employee(session, actor, body)


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: int, session: SessionDep, _: ManagerUser) -> Employee:
    return await employee_service.get_employee(session, employee_id)


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: int, body: EmployeeUpdate, session: SessionDep, actor: ManagerUser
) -> Employee:
    employee = await employee_service.get_employee(session, employee_id)
    return await employee_service.update_employee(session, actor, employee, body)


@router.post("/{employee_id}/account", response_model=EmployeeOut)
async def create_account(
    employee_id: int, body: EmployeeAccountIn, session: SessionDep, actor: ManagerUser
) -> Employee:
    employee = await employee_service.get_employee(session, employee_id)
    return await employee_service.create_account(session, actor, employee, body)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_employee(
    employee_id: int, session: SessionDep, actor: ManagerUser
) -> Response:
    """Marks the employee inactive and disables their login, nothing is deleted."""
    employee = await employee_service.get_employee(session, employee_id)
    await employee_service.deactivate_employee(session, actor, employee)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
