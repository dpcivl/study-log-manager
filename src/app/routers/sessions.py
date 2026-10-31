"""F2 /api/subjects/{id}/sessions, /api/sessions/{id}"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.deps import IdPath, fetch_page, get_subject_or_404
from app.errors import not_found
from app.models import StudySession
from app.schemas import (
    StudySessionCreate,
    StudySessionList,
    StudySessionOut,
    StudySessionUpdate,
)

router = APIRouter(prefix="/api", tags=["F2"], dependencies=[Depends(require_session)])


def _get_session_or_404(db: Session, session_id: int) -> StudySession:
    study_session = db.get(StudySession, session_id)
    if study_session is None:
        raise not_found("session_id")
    return study_session


@router.get("/subjects/{subject_id}/sessions", response_model=StudySessionList)
def list_sessions(
    subject_id: IdPath,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> StudySessionList:
    # 200 목록(studied_on desc, 같은 날은 id desc) + total_minutes / 404
    get_subject_or_404(db, subject_id)
    total, total_minutes = db.execute(
        select(func.count(StudySession.id), func.coalesce(func.sum(StudySession.minutes), 0)).where(
            StudySession.subject_id == subject_id
        )
    ).one()
    items = fetch_page(
        db,
        select(StudySession)
        .where(StudySession.subject_id == subject_id)
        .order_by(StudySession.studied_on.desc(), StudySession.id.desc()),
        page,
        limit,
    )
    return StudySessionList(
        items=[StudySessionOut.model_validate(s) for s in items],
        total=int(total),
        page=page,
        limit=limit,
        total_minutes=int(total_minutes),
    )


@router.post(
    "/subjects/{subject_id}/sessions",
    response_model=StudySessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: StudySessionCreate, subject_id: IdPath, db: Session = Depends(get_db)
) -> StudySessionOut:
    # 201 StudySession / 404 / 422
    get_subject_or_404(db, subject_id)
    study_session = StudySession(
        subject_id=subject_id,
        studied_on=payload.studied_on,
        minutes=payload.minutes,
        memo=payload.memo,
    )
    db.add(study_session)
    db.commit()
    return StudySessionOut.model_validate(study_session)


@router.patch("/sessions/{session_id}", response_model=StudySessionOut)
def update_session(
    payload: StudySessionUpdate, session_id: IdPath, db: Session = Depends(get_db)
) -> StudySessionOut:
    # 보낸 필드만 수정. 200 StudySession / 404 / 422
    study_session = _get_session_or_404(db, session_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(study_session, field, value)
    db.commit()
    return StudySessionOut.model_validate(study_session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: IdPath, db: Session = Depends(get_db)) -> Response:
    # 204 / 404
    study_session = _get_session_or_404(db, session_id)
    db.delete(study_session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
