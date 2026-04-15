"""HTTP middleware for the SKF Racing Hub API."""

from __future__ import annotations

from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_stale_flag: ContextVar[bool] = ContextVar("simgrid_stale_data", default=False)


def mark_stale() -> None:
    """Flag the current request as serving stale cached data.

    Called by ``simgrid_service`` whenever it falls back to a stale cache
    after an upstream API failure. ``StaleHeaderMiddleware`` reads the flag
    after the handler runs and sets the ``X-Data-Stale`` response header.
    """
    _stale_flag.set(True)


class StaleHeaderMiddleware(BaseHTTPMiddleware):
    """Promote the per-request stale flag to an ``X-Data-Stale`` header."""

    async def dispatch(self, request: Request, call_next):
        token = _stale_flag.set(False)
        try:
            response = await call_next(request)
            if _stale_flag.get():
                response.headers["X-Data-Stale"] = "true"
            return response
        finally:
            _stale_flag.reset(token)
