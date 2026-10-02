"""How the API describes itself in ``openapi.json``.

FastAPI generates the document from the routes; this module adds what it
cannot know on its own, so the spec matches what the server really sends:

* errors are RFC 7807 problem documents (see :mod:`app.core.errors`), not
  FastAPI's default validation shape;
* which operations need a session, and which roles;
* the response headers set outside the handlers (paging, ``Location``).

Routes declare only what is specific to them, with :func:`problem_responses`
and :data:`SIMGRID_RESPONSES`; everything that follows from a route's
dependencies and parameters is filled in by :func:`install`.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic.json_schema import models_json_schema

from app.core.errors import PROBLEM_JSON
from app.schemas.base import CamelModel

_SCHEMA_REF = "#/components/schemas/{model}"

DESCRIPTION = """\
REST API of the SKF Racing Hub site.

**Authentication.** A `session_id` cookie, set by the Discord login. Operations
that need a session list it under *security*; the roles they accept are in
`x-required-roles`.

**Errors.** Every error is an `application/problem+json` document (`Problem`).
`code` is a stable machine-readable identifier, `detail` a message that can be
shown to the user. Validation failures (422) also carry `errors`, one entry per
rejected field.

**Paging.** Collections that take `limit` and `offset` return a plain array;
the total is in `X-Total-Count` and neighbouring pages in an RFC 8288 `Link`
header.

**Tracing.** Every response carries `X-Request-ID`; quote it when reporting a
problem.
"""

TAGS = [
    {"name": "Auth", "description": "Discord login and the session cookie."},
    {"name": "Me", "description": "The signed-in user and their driver."},
    {"name": "Users", "description": "Accounts, roles and sessions (admin)."},
    {"name": "Drivers", "description": "Driver directory and BWP licence points."},
    {"name": "Penalty rules", "description": "BWP thresholds and the sanction each one brings."},
    {"name": "Championships", "description": "SimGrid championships, standings and results."},
    {"name": "Race results", "description": "Uploaded result files, one per round (admin)."},
    {"name": "Giveaway", "description": "Giveaway eligibility from the uploaded results (admin)."},
    {"name": "Driver aliases", "description": "Admin-confirmed merges of two spellings of one driver."},
    {"name": "Incidents", "description": "Incident windows, filed incidents and their resolutions."},
    {"name": "Incident rules", "description": "Verdict presets and description snippets for judges."},
    {"name": "Calendar", "description": "The race calendar: SimGrid and custom championships."},
    {"name": "Custom championships", "description": "Championships entered by community managers."},
    {"name": "Communities", "description": "Communities shown on the calendar."},
    {"name": "Catalog", "description": "Simulators and car classes known to SimGrid."},
    {"name": "Regulations", "description": "Regulation pages and their translations."},
    {"name": "Languages", "description": "UI languages and translation bundles."},
    {"name": "YouTube", "description": "The club's streams."},
    {"name": "Caches", "description": "Caches of external data (admin)."},
    {"name": "Legacy", "description": "Pre-v1 endpoints kept for outside clients."},
]


class FieldError(CamelModel):
    field: str
    message: str


class Problem(CamelModel):
    """An RFC 7807 problem document. Every error response has this shape."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str


class ValidationProblem(Problem):
    """A 422: the request did not pass validation."""

    errors: list[FieldError]


def _problem(status_code: int, model: type[Problem] = Problem) -> dict[str, Any]:
    return {
        "description": HTTPStatus(status_code).phrase,
        "content": {PROBLEM_JSON: {"schema": {"$ref": _SCHEMA_REF.format(model=model.__name__)}}},
    }


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """``responses=`` for the errors a route raises beyond what :func:`install` infers."""
    return {code: _problem(code) for code in status_codes}


# For routes that include SimGrid data but survive its outage.
STALE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "headers": {
            "X-Data-Stale": {
                "description": "`true` when SimGrid was unreachable and cached data was served.",
                "schema": {"type": "string", "enum": ["true"]},
            }
        }
    },
}

# For routes served from SimGrid: an outage is a 502 unless a stale cache
# entry can be served instead.
SIMGRID_RESPONSES: dict[int | str, dict[str, Any]] = {**problem_responses(502), **STALE_RESPONSES}

# ``openapi_extra`` for routes whose path id is looked up in SimGrid, not in
# our database: an unknown id surfaces as a 502, never a 404.
NO_404 = {"x-no-404": True}

_PAGE_HEADERS = {
    "X-Total-Count": {
        "description": "Size of the whole collection, across all pages.",
        "schema": {"type": "integer"},
    },
    "Link": {
        "description": "RFC 8288 links to the `next` and `prev` pages, when they exist.",
        "schema": {"type": "string"},
    },
}

_LOCATION_HEADER = {
    "description": "Path of the created resource.",
    "schema": {"type": "string", "format": "uri-reference"},
}


def operation_id(route: APIRoute) -> str:
    """``list_championships`` -> ``listChampionships``. Handler names are unique API-wide."""
    head, *rest = route.name.split("_")
    return head + "".join(part.title() for part in rest)


def _required_roles(route: APIRoute) -> list[str]:
    """Roles accepted by the route's ``require_role`` dependency, if it has one."""
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        roles = getattr(dependant.call, "required_roles", None)
        if roles:
            return list(roles)
        stack.extend(dependant.dependencies)
    return []


def _finish_operation(operation: dict[str, Any], route: APIRoute) -> None:
    responses = operation["responses"]

    if route.summary is None:
        operation["summary"] = route.name.replace("_", " ").capitalize()

    # FastAPI documents its own validation body; the handlers in
    # app.core.errors replace it with a problem document.
    if "422" in responses:
        responses["422"] = _problem(422, ValidationProblem)

    if operation.get("security"):
        responses.setdefault("401", _problem(401))
    roles = _required_roles(route)
    if roles:
        operation["x-required-roles"] = roles
        note = f"Requires role: {', '.join(f'`{r}`' for r in roles)}."
        operation["description"] = "\n\n".join(filter(None, [operation.get("description"), note]))
        responses.setdefault("403", _problem(403))

    no_404 = operation.pop("x-no-404", False)
    parameters = operation.get("parameters", [])
    if any(p["in"] == "path" for p in parameters) and not no_404:
        responses.setdefault("404", _problem(404))

    query = {p["name"] for p in parameters if p["in"] == "query"}
    if {"limit", "offset"} <= query:
        responses["200"].setdefault("headers", {}).update(_PAGE_HEADERS)
    if "201" in responses:
        responses["201"].setdefault("headers", {})["Location"] = _LOCATION_HEADER

    operation["responses"] = dict(sorted(responses.items()))


def _share_error_responses(schema: dict[str, Any]) -> None:
    """Move the repeated error responses to ``components.responses`` and reference them."""
    shared: dict[str, dict[str, Any]] = {}
    for item in schema["paths"].values():
        for operation in item.values():
            for code, response in operation["responses"].items():
                if code[0] in "45":
                    name = HTTPStatus(int(code)).phrase.title().replace(" ", "").replace("-", "")
                    shared[name] = response
                    operation["responses"][code] = {"$ref": f"#/components/responses/{name}"}
    schema["components"]["responses"] = dict(sorted(shared.items()))


def _strip_titles(node: Any) -> None:
    """Drop generated ``title`` strings; a property *named* title is a dict and stays."""
    if isinstance(node, dict):
        if isinstance(node.get("title"), str):
            del node["title"]
        for value in node.values():
            _strip_titles(value)
    elif isinstance(node, list):
        for item in node:
            _strip_titles(item)


def _build(app: FastAPI) -> dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=DESCRIPTION,
        routes=app.routes,
        tags=TAGS,
    )

    for route in app.routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            for method in route.methods:
                _finish_operation(schema["paths"][route.path_format][method.lower()], route)
    _share_error_responses(schema)

    schemas = schema["components"]["schemas"]
    _, definitions = models_json_schema(
        [(Problem, "serialization"), (ValidationProblem, "serialization")],
        ref_template=_SCHEMA_REF,
    )
    schemas.update(definitions["$defs"])
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)
    schema["components"]["schemas"] = dict(sorted(schemas.items()))

    _strip_titles(schema["paths"])
    _strip_titles(schema["components"])
    return schema


def install(app: FastAPI) -> None:
    """Make ``app.openapi()`` return the finished document."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _build(app)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
