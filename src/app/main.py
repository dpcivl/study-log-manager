"""FastAPI 앱 생성, 라우터 등록, 예외 핸들러(오류 응답 모양)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401  (테이블 등록)
from app.auth import LoginRateLimiter, is_logged_in
from app.db import Base, make_engine, make_session_factory
from app.errors import NOT_FOUND_MESSAGES, APIError, validation_fields
from app.routers import auth, export, notes, pages, sessions, subjects
from app.settings import Settings, get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _error_response(status_code: int, code: str, message: str, **extra) -> JSONResponse:
    error = {"code": code, "message": message}
    error.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(status_code=status_code, content={"error": error})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = settings.database_url
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Study Log", lifespan=lifespan, docs_url=None, redoc_url=None)
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
                return _error_response(415, "unsupported_media_type", "JSON 형식으로 보내야 합니다")
        return await call_next(request)

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

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        # 본문 파싱 오류는 의존성(로그인 검사)보다 먼저 나므로 여기서 401을 먼저 가려낸다.
        path = request.url.path
        if (
            path.startswith("/api/")
            and path not in ("/api/login", "/api/logout")
            and not is_logged_in(request)
        ):
            return _error_response(401, "unauthorized", "로그인이 필요합니다")
        # 경로의 id가 정수가 아니거나 범위 밖이면 없는 자원이다(404).
        for err in errors:
            loc = err.get("loc", ())
            if loc and loc[0] == "path" and loc[-1] in NOT_FOUND_MESSAGES:
                return _error_response(404, "not_found", NOT_FOUND_MESSAGES[loc[-1]])
        return _error_response(
            422, "validation_error", "입력값을 확인하세요", fields=validation_fields(errors)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(404, "not_found", "찾을 수 없습니다")
        if exc.status_code == 415:
            return _error_response(415, "unsupported_media_type", "JSON 형식으로 보내야 합니다")
        return _error_response(exc.status_code, "http_error", str(exc.detail))

    return app


app = create_app()
