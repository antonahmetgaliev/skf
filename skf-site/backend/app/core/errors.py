"""Domain errors and RFC 7807 ``application/problem+json`` responses.

Services raise :class:`AppError` subclasses instead of ``HTTPException`` so
they stay independent of the web layer; the handlers registered by
:func:`register_error_handlers` turn every error — ours, Starlette's and
request-validation failures — into the same problem document::

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "Driver not found.", "code": "not_found"}

``detail`` is always a human-readable string, so clients can show it as is.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, detail: str, *, code: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        self.headers = headers


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class Unprocessable(AppError):
    status_code = 422
    code = "validation_error"


class TooManyRequests(AppError):
    status_code = 429
    code = "too_many_requests"


class BadGateway(AppError):
    status_code = 502
    code = "upstream_error"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


def _code_for_status(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


def problem_response(
    status_code: int,
    detail: str,
    *,
    code: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Error"
    body = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code or _code_for_status(status_code),
        **extra,
    }
    return JSONResponse(body, status_code=status_code, headers=headers, media_type=PROBLEM_JSON)


def _format_loc(loc: tuple | list) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or "request"


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return problem_response(exc.status_code, exc.detail, code=exc.code, headers=exc.headers)


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return problem_response(exc.status_code, detail, headers=getattr(exc, "headers", None))


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": _format_loc(e.get("loc", ())), "message": e.get("msg", "Invalid value.")}
        for e in exc.errors()
    ]
    detail = "; ".join(f"{e['field']}: {e['message']}" for e in errors) or "Invalid request."
    return problem_response(422, detail, code="validation_error", errors=errors)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
