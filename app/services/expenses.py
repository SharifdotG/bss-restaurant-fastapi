from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.models import Expense, User
from app.schemas.common import Page
from app.schemas.expense import ExpenseCreate, ExpenseListParams, ExpenseOut, ExpenseUpdate
from app.services.images import ImageFolder, check_image_key, delete_image

EXPENSE_SORTS = {
    "expenseDate": Expense.expense_date,
    "amount": Expense.amount,
    "title": Expense.title,
    "category": Expense.category,
    "createdAt": Expense.created_at,
}
NULLABLE_FIELDS = {"paid_to", "notes", "receipt_key"}


def _expenses():
    return select(Expense).options(selectinload(Expense.created_by))


async def list_expenses(session: AsyncSession, params: ExpenseListParams) -> Page[ExpenseOut]:
    stmt = _expenses()
    if params.category:
        stmt = stmt.where(Expense.category.in_(params.category))
    if params.date_from:
        stmt = stmt.where(Expense.expense_date >= params.date_from)
    if params.date_to:
        stmt = stmt.where(Expense.expense_date <= params.date_to)
    if params.min_amount is not None:
        stmt = stmt.where(Expense.amount >= params.min_amount)
    if params.max_amount is not None:
        stmt = stmt.where(Expense.amount <= params.max_amount)
    term = search_filter(params.search, Expense.title, Expense.paid_to, Expense.notes)
    if term is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(
        stmt, params.sort, EXPENSE_SORTS, default="-expenseDate", tiebreaker=Expense.id
    )
    return await paginate(session, stmt, params, ExpenseOut)


async def get_expense(session: AsyncSession, expense_id: int) -> Expense:
    expense = await session.scalar(
        _expenses().where(Expense.id == expense_id).execution_options(populate_existing=True)
    )
    if expense is None:
        raise NotFoundError("Expense not found")
    return expense


async def create_expense(session: AsyncSession, actor: User, data: ExpenseCreate) -> Expense:
    if data.receipt_key:
        check_image_key(data.receipt_key, ImageFolder.RECEIPTS)

    expense = Expense(**data.model_dump(), created_by_id=actor.id)
    session.add(expense)
    await session.commit()
    return await get_expense(session, expense.id)


async def update_expense(session: AsyncSession, expense: Expense, data: ExpenseUpdate) -> Expense:
    changes = {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if value is not None or field in NULLABLE_FIELDS
    }
    if changes.get("receipt_key"):
        check_image_key(changes["receipt_key"], ImageFolder.RECEIPTS)

    old_receipt = expense.receipt_key
    for field, value in changes.items():
        setattr(expense, field, value)
    await session.commit()

    if old_receipt and old_receipt != expense.receipt_key:
        await delete_image(old_receipt)
    return await get_expense(session, expense.id)


async def delete_expense(session: AsyncSession, expense: Expense) -> None:
    await session.delete(expense)
    await session.commit()
    await delete_image(expense.receipt_key)
