from fastapi import APIRouter

from app.api.v1 import (
    auth,
    categories,
    dashboard,
    employees,
    expenses,
    foods,
    health,
    orders,
    payments,
    public,
    reports,
    restaurant,
    tables,
    uploads,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(public.router)
api_router.include_router(restaurant.router)
api_router.include_router(users.router)
api_router.include_router(uploads.router)
api_router.include_router(categories.router)
api_router.include_router(foods.router)
api_router.include_router(tables.router)
api_router.include_router(employees.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(expenses.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
