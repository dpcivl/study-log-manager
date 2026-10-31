"""라우터가 같이 쓰는 FastAPI 의존성·경로 매개변수·조회 도우미."""

from typing import Annotated

from fastapi import Path
from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.errors import not_found
from app.models import Subject

# SQLite OFFSET이 다룰 수 있는 범위. 넘으면 그 페이지는 비어 있다.
_MAX_OFFSET = 2**62

# 경로의 id. SQLite 정수 범위 안으로 제한한다. 정수가 아니거나 범위 밖이면 없는 자원(404)으로
# 처리된다(main.py의 검증 오류 핸들러가 매개변수 이름으로 errors.NOT_FOUND_MESSAGES를 찾는다).
# Path(...) 인스턴스를 직접 공유하면 FastAPI가 매개변수 이름을 섞으므로 Annotated 별칭으로 쓴다.
IdPath = Annotated[int, Path(ge=1, le=2**63 - 1)]


def get_subject_or_404(db: Session, subject_id: int) -> Subject:
    """주제 하나를 읽는다. 없으면 404 "주제를 찾을 수 없습니다"."""
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise not_found("subject_id")
    return subject


def fetch_page[T](db: Session, stmt: Select[tuple[T]], page: int, limit: int) -> list[T]:
    """정렬이 끝난 질의에서 page쪽(1부터)의 limit개를 읽는다. 범위 밖 쪽은 빈 목록이다."""
    offset = (page - 1) * limit
    if offset >= _MAX_OFFSET:
        return []
    return list(db.scalars(stmt.offset(offset).limit(limit)))
