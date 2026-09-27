from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, ManagerUser, SessionDep
from app.models import Category
from app.schemas.menu import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import categories as category_service

router = APIRouter(prefix="/categories", tags=["menu"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    session: SessionDep, _: CurrentUser, include_inactive: bool = False
) -> list[Category]:
    return await category_service.list_categories(session, include_inactive)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryCreate, session: SessionDep, _: ManagerUser) -> Category:
    return await category_service.create_category(session, body)


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: int, session: SessionDep, _: CurrentUser) -> Category:
    return await category_service.get_category(session, category_id)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, body: CategoryUpdate, session: SessionDep, _: ManagerUser
) -> Category:
    category = await category_service.get_category(session, category_id)
    return await category_service.update_category(session, category, body)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: int, session: SessionDep, _: ManagerUser) -> Response:
    category = await category_service.get_category(session, category_id)
    await category_service.delete_category(session, category)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
