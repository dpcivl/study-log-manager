"""로그인 검사 의존성, 쿠키 발급, 실패 횟수 제한. F5에서 구현한다."""

from fastapi import Request

from app.errors import NotImplementedAPIError

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 2592000초 = 30일
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60


def make_session_token(secret_key: str) -> str:
    """발급 시각이 든 서명 토큰을 만든다."""
    raise NotImplementedAPIError()


def verify_session_token(secret_key: str, token: str) -> bool:
    """서명과 30일 만료를 검사한다."""
    raise NotImplementedAPIError()


class LoginRateLimiter:
    """IP별 연속 실패 5회 → 60초 잠금. 서버 메모리에만 둔다."""

    def __init__(self) -> None:
        raise NotImplementedAPIError()


def require_session(request: Request) -> None:
    """로그인·로그아웃을 제외한 모든 API 의존성. 쿠키가 없거나 만료면 401 unauthorized."""
    raise NotImplementedAPIError()
