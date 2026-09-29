from fastapi import APIRouter

from app.api.v1 import (
    auth,
    categories,
    employees,
    foods,
    health,
    orders,
    tables,
    uploads,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(uploads.router)
api_router.include_router(categories.router)
api_router.include_router(foods.router)
api_router.include_router(tables.router)
api_router.include_router(employees.router)
api_router.include_router(orders.router)
