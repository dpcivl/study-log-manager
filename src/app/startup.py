"""서버 시작 검사(F10). 설정을 읽고 DB를 연다.

시작에 실패하면 원인을 "시작 실패: ..." 한 줄로 알린다. 설정값(비밀번호, SECRET_KEY,
DATABASE_URL)은 담지 않고 설정 이름과 DB 경로만 담는다.
"""

import logging
import os
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError, DBAPIError

from app import models  # noqa: F401  (테이블 등록)
from app.db import Base, file_database_path, is_corrupt_database, make_engine
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

FAILURE_PREFIX = "시작 실패: "


class StartupError(RuntimeError):
    """시작할 수 없다. 메시지는 로그에 그대로 남길 수 있는 "시작 실패: ..." 한 줄이다."""


def load_settings() -> Settings:
    """설정을 읽는다. 형식이 틀리면 한 줄을 남기고 종료 코드 1로 끝낸다."""
    try:
        return get_settings()
    except ValidationError as exc:
        errors = exc.errors()
        loc = errors[0].get("loc", ()) if errors else ()
        name = str(loc[0]).upper() if loc else "?"
        logger.error("%s설정 %s 값이 올바르지 않습니다", FAILURE_PREFIX, name)
        raise SystemExit(1) from None


def _url_error() -> StartupError:
    return StartupError(f"{FAILURE_PREFIX}DATABASE_URL을 확인하세요")


def open_storage(database_url: str) -> Engine:
    """엔진을 만들고 DB를 열어 테이블까지 준비한다. 실패하면 StartupError.

    파일 기반 SQLite DB가 없거나 0바이트면 새로 만들고 경로가 든 경고를 남긴다.
    """
    try:
        engine = make_engine(database_url)
    except (ArgumentError, ImportError, ValueError):  # 형식·쿼리·포트가 틀렸거나 드라이버가 없다
        raise _url_error() from None

    path = file_database_path(database_url)
    try:
        is_new = False
        if path is not None:
            _make_private_dirs(path.parent)
            is_new = _create_private_file(path) or path.stat().st_size == 0
            # 롤백 저널은 첫 쓰기 때 DB와 같은 폴더에 생기므로 폴더도 쓸 수 있어야 한다.
            if not os.access(path.parent, os.W_OK | os.X_OK):
                raise StartupError(_open_message(path))
        if path is not None and not is_new and not os.access(path, os.W_OK):
            raise StartupError(_open_message(path))
        with engine.connect() as conn:
            if path is not None and not is_new:
                # 첫 질의에서 SQLite 파일이 아닌 파일은 DatabaseError가 난다.
                if conn.exec_driver_sql("PRAGMA quick_check").scalar() != "ok":
                    raise StartupError(_corrupt_message(path))
            if path is not None:
                # 쓸 수 있는지 미리 본다. 쓰기 잠금만 잡았다 풀고 아무것도 바꾸지 않는다.
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                conn.rollback()
        Base.metadata.create_all(engine)
    except StartupError:
        engine.dispose()
        raise
    except OSError:
        engine.dispose()
        raise StartupError(_open_message(path)) from None
    except ValueError:  # 연결할 때 드러나는 틀린 쿼리 값(timeout 등). 값은 로그에 담지 않는다
        engine.dispose()
        raise _url_error() from None
    except DBAPIError as exc:
        engine.dispose()
        if path is None:
            raise _url_error() from None
        if is_corrupt_database(exc):
            raise StartupError(_corrupt_message(path)) from None
        raise StartupError(_open_message(path)) from None

    if is_new:
        logger.warning(
            "새 빈 DB를 만들었습니다: %s. 기존 데이터가 있었다면 서버를 멈추고 "
            "DATABASE_URL과 백업을 확인하세요",
            path,
        )
    return engine


def _make_private_dirs(folder: Path) -> None:
    """없는 폴더를 소유자 전용(700)으로 만든다. 상위 폴더도 없으면 같이 만든다.

    이미 있는 폴더의 권한은 바꾸지 않는다.
    """
    missing: list[Path] = []
    current = folder
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for target in reversed(missing):
        try:
            os.mkdir(target, 0o700)
        except FileExistsError:  # 그 사이 다른 프로세스가 만들었다. 우리 것이 아니니 둔다
            continue
        os.chmod(target, 0o700)  # umask와 무관하게 700


def _create_private_file(path: Path) -> bool:
    """DB 파일이 없으면 소유자 전용(600)의 빈 파일로 만들고 True. 있으면 그대로 두고 False."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def _open_message(path) -> str:
    if path is None:
        return f"{FAILURE_PREFIX}DATABASE_URL을 확인하세요"
    return f"{FAILURE_PREFIX}DB를 열 수 없습니다: {path}. 폴더 권한을 확인하세요"


def _corrupt_message(path) -> str:
    return f"{FAILURE_PREFIX}DB 파일이 손상되었습니다: {path}. 백업으로 복원하세요"
