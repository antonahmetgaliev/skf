"""Rules every operation in ``openapi.json`` must follow.

The document is generated, so these guard the conventions rather than any one
route: a new endpoint that breaks one fails here, not in a client.
"""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

from app.core.errors import PROBLEM_JSON
from app.core.openapi import ValidationProblem

_METHODS = {"get", "post", "put", "patch", "delete"}
_CAMEL = re.compile(r"[a-z][A-Za-z0-9]*")


@pytest.fixture(scope="module")
def spec() -> dict:
    from app.main import app

    return app.openapi()


@pytest.fixture(scope="module")
def operations(spec) -> list[tuple[str, dict]]:
    return [
        (f"{method.upper()} {path}", operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in _METHODS
    ]


def test_operation_ids_are_unique_camel_case(operations):
    ids = [op["operationId"] for _, op in operations]
    assert len(ids) == len(set(ids))
    assert [i for i in ids if not _CAMEL.fullmatch(i)] == []


def test_errors_are_shared_problem_documents(spec, operations):
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    shared = spec["components"]["responses"]
    assert all(list(r["content"]) == [PROBLEM_JSON] for r in shared.values())
    inline = [
        f"{name} {code}"
        for name, op in operations
        for code, response in op["responses"].items()
        if code[0] in "45" and response["$ref"].rsplit("/", 1)[-1] not in shared
    ]
    assert inline == []


def test_protected_operations_document_401_and_403(operations):
    missing = [
        name
        for name, op in operations
        if (op.get("security") and "401" not in op["responses"])
        or (op.get("x-required-roles") and "403" not in op["responses"])
    ]
    assert missing == []


def test_every_201_documents_location(operations):
    missing = [
        name
        for name, op in operations
        if "201" in op["responses"] and "Location" not in op["responses"]["201"].get("headers", {})
    ]
    assert missing == []


def test_paged_collections_document_their_headers(operations):
    for name, op in operations:
        query = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
        if {"limit", "offset"} <= query:
            assert {"X-Total-Count", "Link"} <= set(op["responses"]["200"]["headers"]), name


def test_schema_properties_are_camel_case(spec):
    wrong = [
        f"{name}.{prop}"
        for name, schema in spec["components"]["schemas"].items()
        for prop in schema.get("properties", {})
        if not _CAMEL.fullmatch(prop)
    ]
    assert wrong == []


async def test_a_real_validation_error_matches_the_documented_shape(client: AsyncClient):
    resp = await client.get("/api/v1/calendar-events")  # required `year` is missing

    assert resp.status_code == 422
    assert resp.headers["content-type"] == PROBLEM_JSON
    problem = ValidationProblem.model_validate(resp.json())
    assert problem.code == "validation_error"
    assert [e.field for e in problem.errors] == ["year"]


def test_null_defaults_only_where_null_is_allowed(spec):
    """An ``Omittable`` PATCH field must not look nullable to a client."""

    def offenders(node, path=""):
        if isinstance(node, dict):
            if node.get("default", ...) is None and node.get("type") not in (None, "null"):
                yield path
            for key, value in node.items():
                yield from offenders(value, f"{path}/{key}")

    assert list(offenders(spec["components"]["schemas"])) == []
    name = spec["components"]["schemas"]["CommunityUpdate"]["properties"]["name"]
    assert name == {"type": "string", "minLength": 1, "maxLength": 200}
