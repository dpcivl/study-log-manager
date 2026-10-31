"""엔진·세션·Base. 테스트는 :memory: SQLite를 쓴다."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


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
            database_url, connect_args={"check_same_thread": False}, hide_parameters=True
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
