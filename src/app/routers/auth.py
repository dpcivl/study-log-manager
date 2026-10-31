"""F5 POST /api/login, POST /api/logout"""

import hmac

from fastapi import APIRouter, Request, Response, status

from app.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    LoginRateLimiter,
    client_ip,
    make_session_token,
)
from app.errors import APIError
from app.schemas import LoginRequest

router = APIRouter(prefix="/api", tags=["F5"])


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https"


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(payload: LoginRequest, request: Request, response: Response) -> None:
    settings = request.app.state.settings
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = client_ip(request)

    if not settings.secret_key:
        raise APIError(500, "server_misconfigured", "서버 설정이 올바르지 않습니다")

    # 잠금 확인과 시도 예약을 한 번에 한다. 비교 결과를 기다리지 않으므로
    # 동시에 들어온 요청도 5회를 넘겨 시험할 수 없다.
    retry_after = limiter.acquire(ip)
    if retry_after is not None:
        raise APIError(429, "too_many_attempts", "잠시 후 다시 시도하세요", retry_after=retry_after)

    # APP_PASSWORD가 비어 있으면 어떤 입력도 통과시키지 않는다.
    expected = settings.app_password.encode("utf-8")
    try:
        given = payload.password.encode("utf-8")
    except UnicodeEncodeError:
        # 짝 없는 서로게이트 등 인코딩할 수 없는 입력은 틀린 비밀번호로 본다(시도는 이미 셌다).
        given = None
    if not expected or given is None or not hmac.compare_digest(expected, given):
        raise APIError(401, "invalid_password", "비밀번호가 올바르지 않습니다")

    limiter.reset(ip)
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(settings.secret_key),
        max_age=SESSION_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
