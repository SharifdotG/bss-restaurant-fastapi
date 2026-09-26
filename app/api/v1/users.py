from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ManagerUser, SessionDep
from app.models import User
from app.schemas.common import Page
from app.schemas.user import PasswordReset, UserCreate, UserListParams, UserOut, UserUpdate
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
async def list_users(
    session: SessionDep, _: ManagerUser, params: Annotated[UserListParams, Query()]
) -> Page[UserOut]:
    return await user_service.list_users(session, params)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: SessionDep, actor: ManagerUser) -> User:
    return await user_service.create_user(session, body, actor=actor)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: SessionDep, _: ManagerUser) -> User:
    return await user_service.get_user(session, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, body: UserUpdate, session: SessionDep, actor: ManagerUser
) -> User:
    user = await user_service.get_user(session, user_id)
    return await user_service.update_user(session, actor, user, body)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int, body: PasswordReset, session: SessionDep, actor: ManagerUser
) -> Response:
    user = await user_service.get_user(session, user_id)
    await user_service.reset_password(session, actor, user, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(user_id: int, session: SessionDep, actor: ManagerUser) -> Response:
    """Users are never hard deleted, orders and payments keep pointing at them."""
    user = await user_service.get_user(session, user_id)
    await user_service.deactivate_user(session, actor, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
