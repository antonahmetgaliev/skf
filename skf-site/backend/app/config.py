import os

from pydantic import model_validator
from pydantic_settings import BaseSettings


def _fix_async_url(url: str) -> str:
    """Railway gives postgresql://… but asyncpg needs postgresql+asyncpg://…"""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/skf"
    simgrid_api_key: str = ""
    simgrid_base_url: str = "https://www.thesimgrid.com"
    cors_origins: str = "http://localhost:4200"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _normalise_db_url(self) -> "Settings":
        self.database_url = _fix_async_url(self.database_url)
        return self


settings = Settings()
