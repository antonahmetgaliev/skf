from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/skf"
    simgrid_api_key: str = ""
    simgrid_base_url: str = "https://www.thesimgrid.com"
    cors_origins: str = "http://localhost:4200"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
