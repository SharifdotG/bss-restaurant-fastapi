from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ManagerUser, SessionDep
from app.schemas.report import (
    ExpenseReport,
    ReportRange,
    SalesParams,
    SalesReport,
    TopFoodParams,
    TopFoodsReport,
)
from app.services import reports as report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales", response_model=SalesReport)
async def sales(
    session: SessionDep, _: ManagerUser, params: Annotated[SalesParams, Query()]
) -> SalesReport:
    """Paid orders against expenses, one row per day, week, month or year."""
    return await report_service.sales_report(session, params)


@router.get("/top-foods", response_model=TopFoodsReport)
async def top_foods(
    session: SessionDep, _: ManagerUser, params: Annotated[TopFoodParams, Query()]
) -> TopFoodsReport:
    return await report_service.top_foods_report(session, params)


@router.get("/expenses", response_model=ExpenseReport)
async def expenses(
    session: SessionDep, _: ManagerUser, params: Annotated[ReportRange, Query()]
) -> ExpenseReport:
    """Where the money went, per category."""
    return await report_service.expense_report(session, params)
