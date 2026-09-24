import asyncio
import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import SessionDep
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    database: str
    version: str
    environment: str


@router.get("/health", response_model=HealthOut)
async def health(session: SessionDep, response: Response) -> HealthOut:
    db_status = "ok"
    try:
        # a suspended neon compute needs a moment to wake up
        async with asyncio.timeout(5):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.exception("health check could not reach the database")
        db_status = "unreachable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthOut(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        version=__version__,
        environment=settings.environment,
    )
