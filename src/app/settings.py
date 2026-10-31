"""환경 변수. design.md 6절: APP_PASSWORD, SECRET_KEY, DATABASE_URL을 .env에서 읽는다."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_password: str = ""
    secret_key: str = ""
    database_url: str = "sqlite:///data/study.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
