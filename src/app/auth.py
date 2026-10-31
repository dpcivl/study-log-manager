"""로그인 검사 의존성, 쿠키 발급, 실패 횟수 제한. F5."""

import math
import threading
import time
from collections.abc import Callable

from fastapi import Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.errors import APIError

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 2592000초 = 30일
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60

_SESSION_SALT = "study-log-session"
_MAX_TRACKED_IPS = 10_000


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=_SESSION_SALT)


def make_session_token(secret_key: str) -> str:
    """발급 시각이 든 서명 토큰을 만든다."""
    return _serializer(secret_key).dumps("session")


def verify_session_token(secret_key: str, token: str) -> bool:
    """서명과 30일 만료를 검사한다."""
    if not secret_key or not token:
        return False
    try:
        _serializer(secret_key).loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:  # SignatureExpired도 BadSignature의 하위 클래스다
        return False
    return True


class LoginRateLimiter:
    """IP별 연속 실패 5회 → 60초 잠금. 서버 메모리에만 둔다."""

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        lock_seconds: int = LOGIN_LOCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._clock = clock
        self._mutex = threading.Lock()
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def acquire(self, ip: str) -> int | None:
        """시도 한 번을 예약한다. 잠금 확인과 횟수 증가를 한 락 안에서 처리한다.

        잠겨 있으면 남은 초(올림, 최소 1)를 돌려주고 시도는 허용하지 않는다.
        허용하면 None을 돌려준다. 이 시도를 실패로 가정해 연속 실패 횟수를 먼저
        올리므로, 한도(5번째)에 닿은 시도부터는 이후 시도가 모두 잠금에 걸린다.
        비밀번호가 맞으면 호출자가 reset으로 되돌린다.
        """
        with self._mutex:
            now = self._clock()
            until = self._locked_until.get(ip)
            if until is not None:
                remaining = until - now
                if remaining > 0:
                    return max(1, math.ceil(remaining))
                del self._locked_until[ip]
                self._failures.pop(ip, None)
            if len(self._failures) >= _MAX_TRACKED_IPS and ip not in self._failures:
                self._prune()
            count = self._failures.get(ip, 0) + 1
            if count >= self._max_failures:
                self._failures.pop(ip, None)
                self._locked_until[ip] = now + self._lock_seconds
            else:
                self._failures[ip] = count
            return None

    def reset(self, ip: str) -> None:
        """로그인에 성공하면 카운터를 초기화한다."""
        with self._mutex:
            self._failures.pop(ip, None)
            self._locked_until.pop(ip, None)

    def _prune(self) -> None:
        now = self._clock()
        self._locked_until = {k: v for k, v in self._locked_until.items() if v > now}
        self._failures.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    return verify_session_token(request.app.state.settings.secret_key, token)


def require_session(request: Request) -> None:
    """로그인·로그아웃을 제외한 모든 API 의존성. 쿠키가 없거나 만료면 401 unauthorized."""
    if not is_logged_in(request):
        raise APIError(401, "unauthorized", "로그인이 필요합니다")
