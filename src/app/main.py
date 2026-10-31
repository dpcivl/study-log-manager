"""FastAPI 앱 생성, 라우터 등록, 예외 핸들러(오류 응답 모양)."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401  (테이블 등록)
from app.auth import LoginRateLimiter, LoginRedirect, is_logged_in
from app.body_limit import BodySizeLimitMiddleware
from app.db import Base, make_engine, make_session_factory
from app.errors import (
    BODY_INVALID_MESSAGE,
    NOT_FOUND_MESSAGES,
    REQUEST_FIELD,
    APIError,
    error_response,
    validation_fields,
)
from app.routers import auth, export, notes, pages, sessions, subjects
from app.security_headers import SecurityHeadersMiddleware, security_headers
from app.settings import (
    MIN_APP_PASSWORD_LENGTH,
    MIN_SECRET_KEY_LENGTH,
    Settings,
    get_settings,
    weak_secret_problems,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 값 자체는 로그에 남기지 않는다. 어느 설정이 왜 부족한지만 남긴다.
        problems = weak_secret_problems(settings)
        if problems and settings.public_deploy:
            reasons = "; ".join(problems)
            logger.critical("PUBLIC_DEPLOY가 켜져 있어 시작하지 않습니다: %s", reasons)
            raise RuntimeError(
                f"PUBLIC_DEPLOY 상태에서는 약한 설정으로 시작할 수 없습니다: {reasons}"
            )
        if problems:
            logger.warning(
                "약한 설정으로 시작합니다(PUBLIC_DEPLOY가 꺼져 있음): %s. "
                "공개 배포에는 SECRET_KEY %d자 이상, APP_PASSWORD %d자 이상(앞뒤 공백 제외)이 "
                "필요합니다. 이 값으로 인터넷에 공개하지 마세요. "
                "공개할 때는 PUBLIC_DEPLOY=true로 켜세요.",
                "; ".join(problems),
                MIN_SECRET_KEY_LENGTH,
                MIN_APP_PASSWORD_LENGTH,
            )
        url = settings.database_url
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    # redirect_slashes=False: 끝 슬래시 리다이렉트는 쿼리를 엄격히 디코드해 원시 바이트에서
    # 예외가 나고 Location을 Host 헤더로 만든다. 끝 슬래시가 다른 경로는 404 공통 오류다.
    app = FastAPI(
        title="Study Log",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    app.state.settings = settings
    app.state.login_limiter = LoginRateLimiter()  # 앱 인스턴스마다 독립

    @app.middleware("http")
    async def require_json_content_type(request: Request, call_next):
        # 본문이 있는 POST·PATCH는 application/json이어야 한다(415).
        if request.method in ("POST", "PATCH"):
            has_body = request.headers.get("content-length", "0") not in ("", "0") or (
                "transfer-encoding" in request.headers
            )
            media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if has_body and media_type != "application/json":
                return error_response(415, "unsupported_media_type", "JSON 형식으로 보내야 합니다")
        return await call_next(request)

    # 마지막에 더한 미들웨어가 가장 바깥이다. 본문 상한은 415 검사와 인증보다 먼저 끝난다.
    app.add_middleware(BodySizeLimitMiddleware)
    # 보안 헤더는 가장 바깥에 둔다. 본문 상한의 413·400 응답에도 붙어야 한다.
    app.add_middleware(SecurityHeadersMiddleware, public_deploy=settings.public_deploy)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth.router)
    app.include_router(subjects.router)
    app.include_router(sessions.router)
    app.include_router(notes.router)
    app.include_router(export.router)
    app.include_router(pages.router)

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body())

    @app.exception_handler(LoginRedirect)
    async def login_redirect_handler(request: Request, exc: LoginRedirect) -> RedirectResponse:
        return RedirectResponse("/login", status_code=302)

    def unauthorized_before_body(request: Request) -> JSONResponse | None:
        """본문 파싱 오류는 의존성(로그인 검사)보다 먼저 나므로 401을 먼저 가려낸다.

        request.url은 잘못된 UTF-8 쿼리에서 예외가 날 수 있어 ASGI scope의 path를 읽는다.
        """
        path = request.scope["path"]
        if (
            path.startswith("/api/")
            and path not in ("/api/login", "/api/logout")
            and not is_logged_in(request)
        ):
            return error_response(401, "unauthorized", "로그인이 필요합니다")
        return None

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        unauthorized = unauthorized_before_body(request)
        if unauthorized is not None:
            return unauthorized
        # 경로의 id가 정수가 아니거나 범위 밖이면 없는 자원이다(404).
        for err in errors:
            loc = err.get("loc", ())
            if loc and loc[0] == "path" and loc[-1] in NOT_FOUND_MESSAGES:
                return error_response(404, "not_found", NOT_FOUND_MESSAGES[loc[-1]])
        return error_response(
            422, "validation_error", "입력값을 확인하세요", fields=validation_fields(errors)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 405의 Allow 같은 헤더는 예외가 가져온 그대로 내보낸다.
        headers = exc.headers
        if exc.status_code == 404:
            return error_response(404, "not_found", "찾을 수 없습니다", headers=headers)
        if exc.status_code == 415:
            return error_response(
                415, "unsupported_media_type", "JSON 형식으로 보내야 합니다", headers=headers
            )
        if (
            exc.status_code == 400
            and exc.__cause__ is not None
            and request.scope["path"].startswith("/api")
        ):
            # FastAPI가 본문을 읽다 실패(예: 잘못된 UTF-8)하면 영어 400을 낸다. 깨진 JSON과
            # 같은 공통 모양으로 바꾼다.
            unauthorized = unauthorized_before_body(request)
            if unauthorized is not None:
                return unauthorized
            return error_response(
                422,
                "validation_error",
                "입력값을 확인하세요",
                fields={REQUEST_FIELD: BODY_INVALID_MESSAGE},
            )
        return error_response(exc.status_code, "http_error", str(exc.detail), headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # 내부 정보는 응답에 넣지 않고 서버 로그에만 남긴다.
        path = request.scope["path"]
        logger.error("처리되지 않은 예외: %s %r", request.method, path, exc_info=exc)
        # 500 응답은 가장 바깥 미들웨어를 거치지 않으므로 보안 헤더를 직접 붙인다.
        return error_response(
            500,
            "internal_error",
            "서버 오류가 발생했습니다",
            headers=security_headers(path, settings.public_deploy),
        )

    return app


app = create_app()
