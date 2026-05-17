from __future__ import annotations

from pydantic import BaseModel


class RegulationContentOut(BaseModel):
    lang: str
    title: str
    subtitle: str
    content: str


class RegulationPageListItem(BaseModel):
    id: str
    slug: str
    sort_order: int
    is_visible: bool
    title: str


class RegulationPageOut(BaseModel):
    id: str
    slug: str
    sort_order: int
    is_visible: bool
    contents: dict[str, RegulationContentOut]


class RegulationContentUpdate(BaseModel):
    title: str
    subtitle: str = ""
    content: str = ""


class RegulationPageCreate(BaseModel):
    slug: str
    sort_order: int = 0
    is_visible: bool = True
    contents: dict[str, RegulationContentUpdate] = {}


class RegulationPageUpdate(BaseModel):
    slug: str | None = None
    sort_order: int | None = None
    is_visible: bool | None = None
    contents: dict[str, RegulationContentUpdate] | None = None
