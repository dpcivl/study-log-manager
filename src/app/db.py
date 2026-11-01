"""엔진·세션·Base. 테스트는 :memory: SQLite를 쓴다."""

import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

# DB가 잠겨 있을 때 쓰기를 기다리는 시간(초). 넘으면 503 storage_busy다.
BUSY_TIMEOUT_SECONDS = 5

# SQLite 결과 코드(하위 8비트). 확장 코드는 & 0xFF로 기본 코드를 얻는다.
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6
_SQLITE_CORRUPT = 11
_SQLITE_NOTADB = 26


class Base(DeclarativeBase):
    pass


def file_database_path(database_url: str) -> Path | None:
    """파일 기반 SQLite DB의 절대 경로. 메모리 DB이거나 SQLite가 아니면 None."""
    try:
        parsed = make_url(database_url)
    except (ArgumentError, ValueError):
        return None
    database = parsed.database
    if (
        not parsed.drivername.startswith("sqlite")
        or not database
        or database == ":memory:"
        or database.startswith("file:")
    ):
        return None
    return Path(os.path.abspath(database))


def _sqlite_code(exc: DBAPIError) -> int | None:
    code = getattr(exc.orig, "sqlite_errorcode", None)
    return code & 0xFF if isinstance(code, int) else None


def is_storage_busy(exc: DBAPIError) -> bool:
    """잠금 때문에 실패한 일시 장애인지. 잠시 뒤 다시 하면 될 수 있다."""
    if _sqlite_code(exc) in (_SQLITE_BUSY, _SQLITE_LOCKED):
        return True
    message = str(exc.orig).lower()
    return "database is locked" in message or "database table is locked" in message


def is_corrupt_database(exc: DBAPIError) -> bool:
    """SQLite 파일이 아니거나 손상되었다는 오류인지."""
    if _sqlite_code(exc) in (_SQLITE_CORRUPT, _SQLITE_NOTADB):
        return True
    message = str(exc.orig).lower()
    return "malformed" in message or "not a database" in message


def make_engine(database_url: str) -> Engine:
    # hide_parameters: DB 오류가 로그에 남을 때 바인딩된 값(노트 내용 등)이 같이 찍히지 않게 한다.
    if database_url.startswith("sqlite"):
        if ":memory:" in database_url:
            # 모든 연결이 같은 메모리 DB를 보도록 한다.
            return create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                hide_parameters=True,
            )
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_SECONDS},
            hide_parameters=True,
        )
    return create_engine(database_url, hide_parameters=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI 의존성. 앱 상태에 든 세션 팩토리로 요청마다 세션 하나를 연다."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
