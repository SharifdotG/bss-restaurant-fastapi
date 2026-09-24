import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_valid_request_id = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # reuse the id from a proxy/frontend if it looks sane, never log arbitrary header values
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if _valid_request_id.match(incoming) else uuid4().hex
    request_id_var.set(request_id)

    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
