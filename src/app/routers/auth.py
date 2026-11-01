"""F5 POST /api/login, POST /api/logout"""

from fastapi import APIRouter, Request, Response, status

from app.auth import (
    MAX_PASSWORD_LENGTH,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    LoginRateLimiter,
    client_ip,
    make_session_token,
    password_matches,
)
from app.errors import APIError
from app.schemas import LoginRequest

router = APIRouter(prefix="/api", tags=["F5"])


def _cookie_secure(request: Request) -> bool:
    """공개 배포 설정이 켜져 있거나 요청이 https면 Secure를 붙인다. 로그인·로그아웃이 같이 쓴다.

    request.url은 Host 헤더에 영향받으므로 ASGI scope의 scheme을 읽는다.
    """
    return bool(request.app.state.settings.public_deploy) or request.scope["scheme"] == "https"


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(payload: LoginRequest, request: Request, response: Response) -> None:
    settings = request.app.state.settings
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = client_ip(request)

    # APP_PASSWORD나 SECRET_KEY가 비어 있으면 어떤 비밀번호도 맞을 수 없다. 실패 횟수에 세지 않는다.
    if not settings.secret_key.get_secret_value() or not settings.app_password.get_secret_value():
        raise APIError(500, "server_misconfigured", "서버 설정이 올바르지 않습니다")

    # 잠금 확인과 시도 예약을 한 번에 한다. 비교 결과를 기다리지 않으므로
    # 동시에 들어온 요청도 5회를 넘겨 시험할 수 없다.
    retry_after = limiter.acquire(ip)
    if retry_after is not None:
        raise APIError(429, "too_many_attempts", "잠시 후 다시 시도하세요", retry_after=retry_after)

    # 너무 긴 입력은 비교 없이 거부한다. 스키마 max_length는 422가 되므로 여기서 401로 끝낸다.
    # 시도는 위에서 이미 셌다.
    if len(payload.password) > MAX_PASSWORD_LENGTH or not password_matches(
        settings.app_password.get_secret_value(), payload.password
    ):
        raise APIError(401, "invalid_password", "비밀번호가 올바르지 않습니다")

    limiter.reset(ip)
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(settings.secret_key.get_secret_value()),
        max_age=SESSION_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    # 다른 사이트의 폼이 보낸 요청으로 강제 로그아웃되지 않게 한다. 헤더가 없거나 같은 사이트,
    # 사용자가 직접 연 요청(none)이면 지금처럼 쿠키를 지우고 204다.
    if request.headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        raise APIError(403, "forbidden", "다른 사이트에서 보낸 요청입니다")
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )
