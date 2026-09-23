from fastapi import FastAPI

from app import __version__
from app.core.config import settings


def create_app() -> FastAPI:
    docs_on = settings.docs_enabled

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": __version__}

    return app


app = create_app()
