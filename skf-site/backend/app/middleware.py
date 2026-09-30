"""HTTP middleware for the SKF Racing Hub API."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

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


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Give every request an id, put it on log records and echo it back.

    An incoming ``X-Request-ID`` is reused when it looks safe to log. The id
    is also kept on ``request.state`` for the 500 handler, which runs after
    this middleware has already unwound.
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(token)
