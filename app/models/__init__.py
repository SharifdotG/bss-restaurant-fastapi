# import every model module here so Base.metadata is complete for alembic
from app.models.base import Base
from app.models.employee import Employee, Gender
from app.models.menu import Category, DiscountType, Food
from app.models.refresh_token import RefreshToken
from app.models.table import DiningTable
from app.models.user import User, UserRole

__all__ = [
    "Base",
    "Category",
    "DiningTable",
    "DiscountType",
    "Employee",
    "Food",
    "Gender",
    "RefreshToken",
    "User",
    "UserRole",
]
