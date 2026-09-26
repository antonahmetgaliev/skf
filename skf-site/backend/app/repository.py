"""Small data-access helpers shared by routers and services."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import NotFound

T = TypeVar("T")


async def get_or_404(
    db: AsyncSession,
    model: type[T],
    ident: Any,
    *,
    detail: str | None = None,
    options: tuple = (),
) -> T:
    """Load *model* by primary key or raise :class:`NotFound`."""
    if options:
        pk = model.__mapper__.primary_key[0]  # type: ignore[attr-defined]
        obj = (await db.execute(select(model).options(*options).where(pk == ident))).scalar_one_or_none()
    else:
        obj = await db.get(model, ident)
    if obj is None:
        name = getattr(model, "__doc_name__", None) or _humanize(model.__name__)
        raise NotFound(detail or f"{name} not found.")
    return obj


async def next_sort_order(db: AsyncSession, column: InstrumentedAttribute) -> int:
    """The value that puts a new row after every existing one."""
    return (await db.scalar(select(func.coalesce(func.max(column), -1)))) + 1


def _humanize(name: str) -> str:
    out = "".join(f" {c.lower()}" if c.isupper() else c for c in name).strip()
    return out[:1].upper() + out[1:]
