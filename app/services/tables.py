from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.pagination import apply_sort, paginate, search_filter
from app.models import DiningTable
from app.models.table import new_qr_token
from app.schemas.common import Page
from app.schemas.table import TableCreate, TableListParams, TableOut, TableUpdate
from app.services.common import commit_or_conflict
from app.services.images import ImageFolder, check_image_key, delete_image

TABLE_SORTS = {
    "number": DiningTable.number,
    "seats": DiningTable.seats,
    "location": DiningTable.location,
    "createdAt": DiningTable.created_at,
}
NULLABLE_FIELDS = {"location", "image_key"}


async def _ensure_number_free(
    session: AsyncSession, number: str, exclude_id: int | None = None
) -> None:
    stmt = select(DiningTable.id).where(func.lower(DiningTable.number) == number.lower())
    if exclude_id is not None:
        stmt = stmt.where(DiningTable.id != exclude_id)
    if await session.scalar(stmt):
        raise ConflictError(f"Table '{number}' already exists", code="table_exists")


async def list_tables(session: AsyncSession, params: TableListParams) -> Page[TableOut]:
    stmt = select(DiningTable)
    if params.is_active is not None:
        stmt = stmt.where(DiningTable.is_active.is_(params.is_active))
    if params.min_seats is not None:
        stmt = stmt.where(DiningTable.seats >= params.min_seats)
    if (term := search_filter(params.search, DiningTable.number, DiningTable.location)) is not None:
        stmt = stmt.where(term)

    stmt = apply_sort(stmt, params.sort, TABLE_SORTS, default="number", tiebreaker=DiningTable.id)
    return await paginate(session, stmt, params, TableOut)


async def get_table(session: AsyncSession, table_id: int) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None:
        raise NotFoundError("Table not found")
    return table


async def create_table(session: AsyncSession, data: TableCreate) -> DiningTable:
    await _ensure_number_free(session, data.number)
    if data.image_key:
        check_image_key(data.image_key, ImageFolder.TABLES)

    table = DiningTable(**data.model_dump())
    session.add(table)
    await commit_or_conflict(session, "This table number already exists", "table_exists")
    return table


async def update_table(session: AsyncSession, table: DiningTable, data: TableUpdate) -> DiningTable:
    changes = {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if value is not None or field in NULLABLE_FIELDS
    }
    if "number" in changes:
        await _ensure_number_free(session, changes["number"], exclude_id=table.id)
    if changes.get("image_key"):
        check_image_key(changes["image_key"], ImageFolder.TABLES)

    old_image = table.image_key
    for field, value in changes.items():
        setattr(table, field, value)
    await commit_or_conflict(session, "This table number already exists", "table_exists")

    if old_image and old_image != table.image_key:
        await delete_image(old_image)
    return table


async def regenerate_qr_token(session: AsyncSession, table: DiningTable) -> DiningTable:
    """Invalidates printed QR codes, e.g. when someone abuses the old one."""
    table.qr_token = new_qr_token()
    await session.commit()
    return table


async def delete_table(session: AsyncSession, table: DiningTable) -> None:
    await session.delete(table)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(
            "This table has orders, deactivate it instead", code="table_in_use"
        ) from None
    await delete_image(table.image_key)
