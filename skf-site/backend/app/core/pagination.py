"""Offset pagination for collection endpoints.

Responses stay plain JSON arrays; the total goes in ``X-Total-Count`` and
neighbouring pages in an RFC 8288 ``Link`` header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Query, Request, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


def set_page_headers(request: Request, response: Response, page: PageParams, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    links = []

    def link(offset: int, rel: str) -> None:
        url = request.url.include_query_params(limit=page.limit, offset=offset)
        links.append(f'<{url}>; rel="{rel}"')

    if page.offset + page.limit < total:
        link(page.offset + page.limit, "next")
    if page.offset > 0:
        link(max(page.offset - page.limit, 0), "prev")
    if links:
        response.headers["Link"] = ", ".join(links)


async def paginate(
    db: AsyncSession,
    stmt: Select,
    page: PageParams,
    request: Request,
    response: Response,
) -> list[Any]:
    """Run *stmt* for one page of ORM objects and set the paging headers."""
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await db.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    set_page_headers(request, response, page, total or 0)
    return list(rows)


def paginate_list(items: list[Any], page: PageParams, request: Request, response: Response) -> list[Any]:
    """Page an already-built list (for collections assembled in Python)."""
    set_page_headers(request, response, page, len(items))
    return items[page.offset : page.offset + page.limit]
