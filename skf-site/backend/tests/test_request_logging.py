"""Request ids and the catch-all 500 handler."""

import logging

import httpx
from fastapi import FastAPI

from app.core.errors import register_error_handlers
from app.core.logging import RequestIdFilter
from app.middleware import RequestIdMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/ok")
    async def ok():
        logging.getLogger("app.test").info("inside handler")
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_request_id_is_echoed_and_attached_to_logs(caplog):
    caplog.handler.addFilter(RequestIdFilter())
    async with _client(_app()) as ac:
        with caplog.at_level(logging.INFO, logger="app.test"):
            r = await ac.get("/ok", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert [rec.request_id for rec in caplog.records if rec.name == "app.test"] == ["abc123"]


async def test_request_id_is_generated_when_missing():
    async with _client(_app()) as ac:
        r = await ac.get("/ok")
    assert len(r.headers["X-Request-ID"]) == 12


async def test_unhandled_error_is_logged_and_returned_as_problem(caplog):
    async with _client(_app()) as ac:
        with caplog.at_level(logging.ERROR, logger="app.errors"):
            r = await ac.get("/boom", headers={"X-Request-ID": "req-1"})
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["code"] == "internal_server_error"
    assert body["requestId"] == "req-1"
    assert "kaboom" not in body["detail"]
    [record] = [rec for rec in caplog.records if rec.name == "app.errors"]
    assert "GET /boom" in record.getMessage() and "RuntimeError: kaboom" in record.getMessage()
