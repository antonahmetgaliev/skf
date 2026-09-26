from pydantic import Field

from app.schemas.base import CamelModel, OrmCamelModel


class LanguageCreate(CamelModel):
    code: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)


class LanguageOut(OrmCamelModel):
    code: str
    name: str
    is_active: bool
