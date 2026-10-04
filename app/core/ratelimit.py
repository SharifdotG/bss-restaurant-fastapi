"""A small in-memory rate limiter.

Counts live inside the process, so with several instances each one counts on its own.
That's fine for stopping password guessing and order spam. A shared store like redis
would be the next step if it ever isn't.
"""

import math
import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import TooManyRequestsError

# the longest window used anywhere, keys idle for longer than this can be dropped
LONGEST_WINDOW = 3600


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window: int) -> None:
        """Counts a request for `key`, raises after `limit` of them within `window` seconds."""
        if not settings.rate_limit_enabled:
            return
        now = time.monotonic()
        self._sweep(now)

        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            raise TooManyRequestsError(retry_after=math.ceil(hits[0] + window - now))
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()

    def _sweep(self, now: float) -> None:
        # once a minute forget keys nobody used in a while, so memory doesn't keep growing
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        stale = [
            key for key, hits in self._hits.items() if not hits or hits[-1] < now - LONGEST_WINDOW
        ]
        for key in stale:
            del self._hits[key]


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    hops = settings.trusted_proxy_hops
    if hops:
        # each proxy appends the address it got the request from, so the entry added by
        # the outermost trusted proxy is the client. anything left of it can be made up
        forwarded = [
            part.strip()
            for part in request.headers.get("x-forwarded-for", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window: int) -> Callable[[Request], Awaitable[None]]:
    """Dependency that allows `limit` requests per `window` seconds from one ip."""

    async def check(request: Request) -> None:
        limiter.hit(f"{name}:{client_ip(request)}", limit, window)

    return check
