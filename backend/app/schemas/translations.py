from pydantic import Field

from app.schemas.base import CamelModel, OrmCamelModel

LANGUAGE_CODE_PATTERN = r"^[A-Za-z0-9_-]+$"
LANGUAGE_CODE_MAX_LENGTH = 10


class LanguageCreate(CamelModel):
    code: str = Field(min_length=1, max_length=LANGUAGE_CODE_MAX_LENGTH, pattern=LANGUAGE_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=100)


class LanguageOut(OrmCamelModel):
    code: str
    name: str
    is_active: bool
