"""로그인 검사 의존성, 쿠키 발급, 실패 횟수 제한. F5."""

import hashlib
import hmac
import ipaddress
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
MAX_PASSWORD_LENGTH = 1024  # 이보다 긴 비밀번호는 비교 없이 거부한다

_SESSION_SALT = "study-log-session"
_MAX_TRACKED_IPS = 10_000


def rate_limit_key(host: str) -> str:
    """실패 제한이 세는 단위. IPv6는 /64 대역 문자열로 묶고, 그 밖에는 주소 그대로 쓴다.

    IPv4와 IPv4-mapped IPv6(::ffff:a.b.c.d)는 주소 그대로이고, 파싱할 수 없는 값도 그대로다.
    같은 /64를 쓰는 사용자가 주소를 바꿔 가며 시도해도 같은 카운터를 쓰게 하려는 것이다.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host
    if addr.version == 6 and addr.ipv4_mapped is None:
        return str(ipaddress.IPv6Network((int(addr), 64), strict=False))
    return host


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
    """IP별 연속 실패 5회 → 60초 잠금. 서버 메모리에만 둔다.

    IP는 rate_limit_key로 묶은 값(IPv6는 /64)으로 센다. 추적하는 항목은 _failures와
    _locked_until을 합쳐 상한을 넘지 않게 하고, 넘으면 오래된 것부터 지운다.
    """

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        lock_seconds: int = LOGIN_LOCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int | None = None,
    ) -> None:
        self._max_failures = max_failures
        self._lock_seconds = lock_seconds
        self._clock = clock
        self._max_tracked = max_tracked
        self._mutex = threading.Lock()
        # 두 dict 모두 앞쪽이 오래된 항목이다(실패가 늘 때마다 뒤로 옮긴다).
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def acquire(self, ip: str) -> int | None:
        """시도 한 번을 예약한다. 잠금 확인과 횟수 증가를 한 락 안에서 처리한다.

        잠겨 있으면 남은 초(올림, 최소 1)를 돌려주고 시도는 허용하지 않는다.
        허용하면 None을 돌려준다. 이 시도를 실패로 가정해 연속 실패 횟수를 먼저
        올리므로, 한도(5번째)에 닿은 시도부터는 이후 시도가 모두 잠금에 걸린다.
        비밀번호가 맞으면 호출자가 reset으로 되돌린다.
        """
        key = rate_limit_key(ip)
        with self._mutex:
            now = self._clock()
            self._drop_expired(now)
            until = self._locked_until.get(key)
            if until is not None:
                return max(1, math.ceil(until - now))
            if key not in self._failures:
                self._make_room()
            count = self._failures.pop(key, 0) + 1
            if count >= self._max_failures:
                self._locked_until[key] = now + self._lock_seconds
            else:
                self._failures[key] = count
            return None

    def reset(self, ip: str) -> None:
        """로그인에 성공하면 카운터를 초기화한다."""
        key = rate_limit_key(ip)
        with self._mutex:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _drop_expired(self, now: float) -> None:
        for key in [k for k, until in self._locked_until.items() if until <= now]:
            del self._locked_until[key]

    def _make_room(self) -> None:
        """새 항목 하나를 넣을 자리를 만든다. 전체를 비우지 않고 오래된 것부터 지운다.

        진행 중인 잠금은 마지막까지 남기려고 실패 횟수만 있는 항목을 먼저 지운다.
        """
        limit = _MAX_TRACKED_IPS if self._max_tracked is None else self._max_tracked
        while self._failures or self._locked_until:
            if len(self._failures) + len(self._locked_until) < limit:
                return
            if self._failures:
                del self._failures[next(iter(self._failures))]
            else:
                del self._locked_until[next(iter(self._locked_until))]


def password_matches(expected: str, given: str) -> bool:
    """APP_PASSWORD와 입력을 SHA-256으로 만든 뒤 비교한다(길이가 비교 시간에 드러나지 않게).

    expected가 비어 있으면 어떤 입력도 통과시키지 않는다.
    """
    if not expected:
        return False
    try:
        expected_bytes = expected.encode("utf-8")
        given_bytes = given.encode("utf-8")
    except UnicodeEncodeError:
        # 짝 없는 서로게이트 등 인코딩할 수 없는 입력은 틀린 비밀번호로 본다.
        return False
    return hmac.compare_digest(
        hashlib.sha256(expected_bytes).digest(), hashlib.sha256(given_bytes).digest()
    )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    return verify_session_token(request.app.state.settings.secret_key.get_secret_value(), token)


def require_session(request: Request) -> None:
    """로그인·로그아웃을 제외한 모든 API 의존성. 쿠키가 없거나 만료면 401 unauthorized."""
    if not is_logged_in(request):
        raise APIError(401, "unauthorized", "로그인이 필요합니다")


class LoginRedirect(Exception):
    """화면 주소에 로그인 없이 왔다. main.py의 처리기가 302 /login으로 바꾼다."""


def require_page_login(request: Request) -> None:
    """로그인 화면을 뺀 모든 화면의 의존성. 경로 매개변수 검증보다 먼저 돌아 미로그인이면 302."""
    if not is_logged_in(request):
        raise LoginRedirect
