from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_roles
from app.models import User, UserRole
from app.schemas.report import Dashboard
from app.services import dashboard as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["reports"])

CanView = Annotated[User, Depends(require_roles(UserRole.MANAGER, UserRole.CASHIER))]


@router.get("", response_model=Dashboard)
async def get_dashboard(session: SessionDep, _: CanView) -> Dashboard:
    return await dashboard_service.get_dashboard(session)
