import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.extra = extra
        super().__init__(self.message)


class BadRequestError(AppError):
    pass


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    message = "Could not validate credentials"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You don't have permission to do this"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists or is in a conflicting state"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"
    message = "The uploaded file is too large"


def error_body(detail: Any, code: str, **extra: Any) -> dict[str, Any]:
    return {"detail": detail, "code": code, **extra}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body = error_body(exc.message, exc.code, **(exc.extra or {}))
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
    return JSONResponse(body, status_code=exc.status_code, headers=headers)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            # drop the "body"/"query" prefix, the frontend only cares about the field
            "field": ".".join(str(part) for part in err["loc"][1:]) or str(err["loc"][0]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        error_body("Request validation failed", "validation_error", errors=errors),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        error_body(exc.detail, f"http_{exc.status_code}"),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # services should catch these themselves, this is only a safety net so a
    # unique violation never ends up as a 500
    logger.warning(
        "unhandled integrity error on %s %s: %s", request.method, request.url.path, exc.orig
    )
    return JSONResponse(
        error_body("The request conflicts with existing data", "conflict"),
        status_code=status.HTTP_409_CONFLICT,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        error_body("Internal server error", "internal_error"),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
