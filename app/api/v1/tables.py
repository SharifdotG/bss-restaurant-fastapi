from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, ManagerUser, SessionDep
from app.models import DiningTable
from app.schemas.common import Page
from app.schemas.table import TableCreate, TableListParams, TableOut, TableUpdate
from app.services import tables as table_service

router = APIRouter(prefix="/tables", tags=["tables"])


@router.get("", response_model=Page[TableOut])
async def list_tables(
    session: SessionDep, _: CurrentUser, params: Annotated[TableListParams, Query()]
) -> Page[TableOut]:
    return await table_service.list_tables(session, params)


@router.post("", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(body: TableCreate, session: SessionDep, _: ManagerUser) -> DiningTable:
    return await table_service.create_table(session, body)


@router.get("/{table_id}", response_model=TableOut)
async def get_table(table_id: int, session: SessionDep, _: CurrentUser) -> DiningTable:
    return await table_service.get_table(session, table_id)


@router.patch("/{table_id}", response_model=TableOut)
async def update_table(
    table_id: int, body: TableUpdate, session: SessionDep, _: ManagerUser
) -> DiningTable:
    table = await table_service.get_table(session, table_id)
    return await table_service.update_table(session, table, body)


@router.post("/{table_id}/qr-token", response_model=TableOut)
async def regenerate_qr_token(table_id: int, session: SessionDep, _: ManagerUser) -> DiningTable:
    table = await table_service.get_table(session, table_id)
    return await table_service.regenerate_qr_token(session, table)


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(table_id: int, session: SessionDep, _: ManagerUser) -> Response:
    table = await table_service.get_table(session, table_id)
    await table_service.delete_table(session, table)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
