"""환경 변수. design.md 6절: APP_PASSWORD, SECRET_KEY, DATABASE_URL을 .env에서 읽는다.

PUBLIC_DEPLOY를 켜면 약한 SECRET_KEY·APP_PASSWORD로는 앱이 시작되지 않는다(SEC-1).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# 프로젝트 폴더(src/의 부모). .env와 상대 경로 DB는 실행한 폴더가 아니라 여기를 기준으로 찾는다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

MIN_SECRET_KEY_LENGTH = 32
MIN_APP_PASSWORD_LENGTH = 12


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_password: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")
    database_url: str = "sqlite:///data/study.db"
    public_deploy: bool = False

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite_path(cls, value: str) -> str:
        return anchor_sqlite_url(value)


def anchor_sqlite_url(url: str) -> str:
    """상대 경로의 SQLite 파일 URL을 프로젝트 폴더 기준 절대 경로로 바꾼다.

    메모리 DB, 절대 경로, SQLite가 아닌 URL, 해석할 수 없는 URL은 그대로 둔다.
    형식 오류는 여기서 거부하지 않는다. 시작할 때 DATABASE_URL 오류로 알린다.
    """
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):  # 포트·쿼리 값이 틀린 URL도 시작할 때 알린다
        return url
    database = parsed.database
    if (
        not parsed.drivername.startswith("sqlite")
        or not database
        or database == ":memory:"
        or database.startswith("file:")
        or parsed.query.get("uri")
        or Path(database).is_absolute()
    ):
        return url
    return parsed.set(database=str(PROJECT_ROOT / database)).render_as_string(hide_password=False)


def _weakness(name: str, value: str, min_length: int) -> str | None:
    """값이 약하면 이유를 돌려준다. 이유에는 값(과 그 길이)을 담지 않는다."""
    if not value:
        return f"{name}이(가) 비어 있습니다"
    if not value.strip():
        return f"{name}이(가) 공백뿐입니다"
    if len(value.strip()) < min_length:  # 앞뒤 공백은 길이에 세지 않는다
        return f"{name}이(가) 최소 길이({min_length}자, 앞뒤 공백 제외)보다 짧습니다"
    return None


def weak_secret_problems(settings: Settings) -> list[str]:
    """SECRET_KEY와 APP_PASSWORD가 기준에 못 미치는 이유 목록. 기준을 만족하면 빈 목록."""
    checks = (
        ("SECRET_KEY", settings.secret_key.get_secret_value(), MIN_SECRET_KEY_LENGTH),
        ("APP_PASSWORD", settings.app_password.get_secret_value(), MIN_APP_PASSWORD_LENGTH),
    )
    return [p for name, value, n in checks if (p := _weakness(name, value, n)) is not None]


@lru_cache
def get_settings() -> Settings:
    return Settings()
