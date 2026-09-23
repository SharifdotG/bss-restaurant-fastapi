# import every model module here so Base.metadata is complete for alembic
from app.models.base import Base

__all__ = ["Base"]
