from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ManagerUser, SessionDep
from app.schemas.report import TopFoodParams, TopFoodsReport
from app.services import reports as report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/top-foods", response_model=TopFoodsReport)
async def top_foods(
    session: SessionDep, _: ManagerUser, params: Annotated[TopFoodParams, Query()]
) -> TopFoodsReport:
    return await report_service.top_foods_report(session, params)
