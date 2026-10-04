from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import ManagerUser, SessionDep
from app.core.export import csv_response
from app.core.timeutils import restaurant_tz
from app.schemas.report import (
    ExpenseReport,
    ReportRange,
    SalesParams,
    SalesReport,
    StaffReport,
    TopFoodParams,
    TopFoodsReport,
)
from app.services import reports as report_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _filename(name: str, params: ReportRange) -> str:
    return f"{name}-{params.start}-to-{params.end}.csv"


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


@router.get("/staff", response_model=StaffReport)
async def staff(
    session: SessionDep, _: ManagerUser, params: Annotated[ReportRange, Query()]
) -> StaffReport:
    """How much each waiter sold, best first."""
    return await report_service.staff_report(session, params)


# csv versions of the same reports, for spreadsheets


@router.get("/sales.csv", response_class=Response)
async def sales_csv(
    session: SessionDep, _: ManagerUser, params: Annotated[SalesParams, Query()]
) -> Response:
    report = await report_service.sales_report(session, params)
    return csv_response(
        _filename("sales", params),
        [
            "From",
            "To",
            "Orders",
            "Sales",
            "Discounts",
            "VAT",
            "Refunds",
            "Expenses",
            "Profit",
            "Average order",
        ],
        (
            [
                r.period_start,
                r.period_end,
                r.orders,
                r.sales,
                r.discounts,
                r.vat,
                r.refunds,
                r.expenses,
                r.profit,
                r.average_order,
            ]
            for r in report.rows
        ),
    )


@router.get("/top-foods.csv", response_class=Response)
async def top_foods_csv(
    session: SessionDep, _: ManagerUser, params: Annotated[TopFoodParams, Query()]
) -> Response:
    report = await report_service.top_foods_report(session, params)
    return csv_response(
        _filename("top-foods", params),
        ["Food", "Category", "Quantity", "Orders", "Revenue"],
        ([f.name, f.category, f.quantity, f.orders, f.revenue] for f in report.items),
    )


@router.get("/expenses.csv", response_class=Response)
async def expenses_csv(
    session: SessionDep, _: ManagerUser, params: Annotated[ReportRange, Query()]
) -> Response:
    report = await report_service.expense_report(session, params)
    return csv_response(
        _filename("expenses", params),
        ["Category", "Count", "Amount", "Share %"],
        ([c.category, c.count, c.amount, c.share] for c in report.categories),
    )


@router.get("/staff.csv", response_class=Response)
async def staff_csv(
    session: SessionDep, _: ManagerUser, params: Annotated[ReportRange, Query()]
) -> Response:
    report = await report_service.staff_report(session, params)
    return csv_response(
        _filename("staff", params),
        ["Employee", "Designation", "Orders", "Items sold", "Sales", "Average order", "Cancelled"],
        (
            [
                r.employee.full_name,
                r.employee.designation,
                r.orders,
                r.items_sold,
                r.sales,
                r.average_order,
                r.cancelled,
            ]
            for r in report.rows
        ),
    )


@router.get("/orders.csv", response_class=Response)
async def orders_csv(
    session: SessionDep, _: ManagerUser, params: Annotated[ReportRange, Query()]
) -> Response:
    """Paid and cancelled orders one per line, times are in restaurant time."""
    rows = await report_service.closed_orders(session, params)
    tz = restaurant_tz()
    return csv_response(
        _filename("orders", params),
        [
            "Order",
            "Closed at",
            "Status",
            "Type",
            "Table",
            "Waiter",
            "Items",
            "Subtotal",
            "Discount",
            "Service charge",
            "VAT",
            "Total",
            "Cancel reason",
        ],
        (
            [
                order.order_number,
                order.closed_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                order.status,
                order.order_type,
                order.table.number if order.table else None,
                order.waiter.full_name if order.waiter else None,
                items,
                order.subtotal,
                order.discount_total,
                order.service_charge,
                order.vat,
                order.total,
                order.cancel_reason,
            ]
            for order, items in rows
        ),
    )
