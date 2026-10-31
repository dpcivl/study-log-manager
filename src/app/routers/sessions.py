"""F2 /api/subjects/{id}/sessions, /api/sessions/{id}"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.errors import NotImplementedAPIError
from app.schemas import (
    StudySessionCreate,
    StudySessionList,
    StudySessionOut,
    StudySessionUpdate,
)

router = APIRouter(prefix="/api", tags=["F2"], dependencies=[Depends(require_session)])


@router.get("/subjects/{subject_id}/sessions", response_model=StudySessionList)
def list_sessions(
    subject_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> StudySessionList:
    # 200 목록(studied_on desc, 같은 날은 id desc) + total_minutes / 404
    raise NotImplementedAPIError()


@router.post(
    "/subjects/{subject_id}/sessions",
    response_model=StudySessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    subject_id: int, payload: StudySessionCreate, db: Session = Depends(get_db)
) -> StudySessionOut:
    # 201 StudySession / 404 / 422
    raise NotImplementedAPIError()


@router.patch("/sessions/{session_id}", response_model=StudySessionOut)
def update_session(
    session_id: int, payload: StudySessionUpdate, db: Session = Depends(get_db)
) -> StudySessionOut:
    # 200 StudySession / 404 / 422
    raise NotImplementedAPIError()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, db: Session = Depends(get_db)) -> None:
    # 204 / 404
    raise NotImplementedAPIError()
