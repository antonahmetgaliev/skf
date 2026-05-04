from pydantic import BaseModel


class LanguageCreate(BaseModel):
    code: str
    name: str


class LanguageOut(BaseModel):
    code: str
    name: str
    is_active: bool


class TranslationItem(BaseModel):
    key: str
    value: str


class TranslationBulkUpdate(BaseModel):
    items: list[TranslationItem]
