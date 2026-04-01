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

    # YouTube Data API
    youtube_api_key: str
    youtube_channel_id: str

    # Discord OAuth2
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = "http://localhost:4200/api/auth/discord/callback"

    # Discord guild (used to fetch server-specific nicknames for driver matching)
    discord_guild_id: str = ""
    discord_bot_token: str = ""

    # Session
    session_secret: str = "change-me-in-production"
    session_max_age_hours: int = 24 * 7  # 1 week

    # Bootstrap super-admin on first login by Discord user ID
    super_admin_discord_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _normalise_db_url(self) -> "Settings":
        self.database_url = _fix_async_url(self.database_url)
        return self


settings = Settings()
