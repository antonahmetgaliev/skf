from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field

from app.schemas.base import CamelModel, Omittable


class RegulationContentOut(CamelModel):
    lang: str
    title: str
    subtitle: str
    content: str


class RegulationPageListItem(CamelModel):
    id: uuid.UUID
    slug: str
    sort_order: int
    is_visible: bool
    title: str


class RegulationPageOut(CamelModel):
    id: uuid.UUID
    slug: str
    sort_order: int
    is_visible: bool
    contents: dict[str, RegulationContentOut]


class RegulationContentUpdate(CamelModel):
    title: str = Field(max_length=300)
    subtitle: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=200_000)


class RegulationPageCreate(CamelModel):
    slug: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    is_visible: bool = True
    contents: dict[str, RegulationContentUpdate] = {}


class RegulationPageUpdate(CamelModel):
    slug: Omittable[Annotated[str, Field(min_length=1, max_length=100)]] = None
    sort_order: Omittable[int] = None
    is_visible: Omittable[bool] = None
    contents: Omittable[dict[str, RegulationContentUpdate]] = None
