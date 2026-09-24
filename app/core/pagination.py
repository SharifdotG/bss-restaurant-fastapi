import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.exceptions import BadRequestError
from app.schemas.common import ListParams, Page

type Sortable = InstrumentedAttribute[Any] | ColumnElement[Any]


def search_filter(term: str | None, *columns: Sortable) -> ColumnElement[bool] | None:
    """Case-insensitive "contains" over the given columns, None when there's nothing to search."""
    if not term or not term.strip():
        return None
    # treat % and _ typed by the user literally
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(*(col.ilike(pattern, escape="\\") for col in columns))


def apply_sort(
    stmt: Select[Any],
    sort: str | None,
    allowed: Mapping[str, Sortable],
    default: str,
    tiebreaker: Sortable | None = None,
) -> Select[Any]:
    clauses = []
    for raw in (sort or default).split(","):
        field = raw.strip()
        if not field:
            continue
        descending = field.startswith("-")
        key = field.lstrip("+-")
        column = allowed.get(key)
        if column is None:
            raise BadRequestError(
                f"Can't sort by '{key}'",
                code="invalid_sort",
                extra={"allowed": sorted(allowed)},
            )
        clauses.append(column.desc() if descending else column.asc())

    # keeps page boundaries stable when the sort column has duplicates
    if tiebreaker is not None:
        clauses.append(tiebreaker.asc())
    return stmt.order_by(*clauses)


async def paginate[S: BaseModel](
    session: AsyncSession,
    stmt: Select[Any],
    params: ListParams,
    schema: type[S],
) -> Page[S]:
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = await session.scalar(count_stmt) or 0

    result = await session.execute(stmt.limit(params.size).offset(params.offset))
    # select(Model) -> ORM objects, select(a, b, c) -> rows with named attributes
    rows = result.scalars().all() if len(stmt.column_descriptions) == 1 else result.all()

    return Page[schema](
        items=[schema.model_validate(row) for row in rows],
        total=total,
        page=params.page,
        size=params.size,
        pages=math.ceil(total / params.size) if total else 0,
    )
