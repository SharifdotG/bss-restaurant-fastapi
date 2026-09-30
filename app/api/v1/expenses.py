from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ManagerUser, SessionDep, require_roles
from app.models import Expense, User, UserRole
from app.schemas.common import Page
from app.schemas.expense import ExpenseCreate, ExpenseListParams, ExpenseOut, ExpenseUpdate
from app.services import expenses as expense_service

router = APIRouter(prefix="/expenses", tags=["expenses"])

Accounts = Annotated[User, Depends(require_roles(UserRole.MANAGER, UserRole.CASHIER))]


@router.get("", response_model=Page[ExpenseOut])
async def list_expenses(
    session: SessionDep, _: Accounts, params: Annotated[ExpenseListParams, Query()]
) -> Page[ExpenseOut]:
    return await expense_service.list_expenses(session, params)


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_expense(body: ExpenseCreate, session: SessionDep, actor: Accounts) -> Expense:
    return await expense_service.create_expense(session, actor, body)


@router.get("/{expense_id}", response_model=ExpenseOut)
async def get_expense(expense_id: int, session: SessionDep, _: Accounts) -> Expense:
    return await expense_service.get_expense(session, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: int, body: ExpenseUpdate, session: SessionDep, _: Accounts
) -> Expense:
    expense = await expense_service.get_expense(session, expense_id)
    return await expense_service.update_expense(session, expense, body)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: int, session: SessionDep, _: ManagerUser) -> Response:
    expense = await expense_service.get_expense(session, expense_id)
    await expense_service.delete_expense(session, expense)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
