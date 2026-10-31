"""환경 변수. design.md 6절: APP_PASSWORD, SECRET_KEY, DATABASE_URL을 .env에서 읽는다.

PUBLIC_DEPLOY를 켜면 약한 SECRET_KEY·APP_PASSWORD로는 앱이 시작되지 않는다(SEC-1).
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_KEY_LENGTH = 32
MIN_APP_PASSWORD_LENGTH = 12


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_password: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")
    database_url: str = "sqlite:///data/study.db"
    public_deploy: bool = False


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
