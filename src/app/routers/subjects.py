"""F1 /api/subjects"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.auth import require_session
from app.clock import today_kst
from app.db import get_db
from app.deps import IdPath, get_subject_or_404
from app.errors import TARGET_BEFORE_START_MESSAGE, APIError
from app.models import Note, StudySession, Subject
from app.schemas import SubjectCreate, SubjectList, SubjectOut, SubjectUpdate

router = APIRouter(prefix="/api/subjects", tags=["F1"], dependencies=[Depends(require_session)])


def _stats(db: Session, subject_id: int | None = None) -> dict[int, dict[str, int]]:
    """주제별 계산 필드를 질의 두 번(공부 기록 집계, 노트 집계)으로 구한다.

    subject_id를 주면 그 주제만, 없으면 모든 주제를 집계한다.
    last7_minutes는 오늘 포함 7일(KST)이다.
    """
    today = today_kst()
    week_start: date = today - timedelta(days=6)

    session_query = select(
        StudySession.subject_id,
        func.sum(StudySession.minutes),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            StudySession.studied_on >= week_start,
                            StudySession.studied_on <= today,
                        ),
                        StudySession.minutes,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.count(func.distinct(StudySession.studied_on)),
    ).group_by(StudySession.subject_id)
    note_query = select(
        Note.subject_id,
        func.count(Note.id),
        func.coalesce(func.sum(case((Note.is_open.is_(True), 1), else_=0)), 0),
    ).group_by(Note.subject_id)
    if subject_id is not None:
        session_query = session_query.where(StudySession.subject_id == subject_id)
        note_query = note_query.where(Note.subject_id == subject_id)

    stats: dict[int, dict[str, int]] = {}
    for sid, total, last7, days in db.execute(session_query):
        stats.setdefault(sid, {}).update(
            total_minutes=int(total or 0), last7_minutes=int(last7), days_studied=int(days)
        )
    for sid, count, open_count in db.execute(note_query):
        stats.setdefault(sid, {}).update(note_count=int(count), open_note_count=int(open_count))
    return stats


def _check_date_order(started_on: date, target_date: date | None) -> None:
    """F12: 목표일이 시작일보다 빠르면 422 fields.target_date. 목표일이 없거나 같은 날이면 통과."""
    if target_date is not None and target_date < started_on:
        raise APIError(
            422,
            "validation_error",
            "입력값을 확인하세요",
            fields={"target_date": TARGET_BEFORE_START_MESSAGE},
        )


def _to_out(subject: Subject, stats: dict[int, dict[str, int]]) -> SubjectOut:
    return SubjectOut.model_validate(subject).model_copy(update=stats.get(subject.id, {}))


@router.get("", response_model=SubjectList)
def list_subjects(db: Session = Depends(get_db)) -> SubjectList:
    # 200 {items:[Subject+계산필드]} 생성 최신순(같은 시각이면 id가 큰 쪽이 먼저)
    subjects = db.scalars(select(Subject).order_by(Subject.created_at.desc(), Subject.id.desc()))
    stats = _stats(db)
    return SubjectList(items=[_to_out(s, stats) for s in subjects])


@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)) -> SubjectOut:
    # 201 Subject+계산필드(모두 0) / 422 validation_error
    _check_date_order(payload.started_on, payload.target_date)
    subject = Subject(
        name=payload.name,
        background=payload.background,
        started_on=payload.started_on,
        target_date=payload.target_date,
    )
    db.add(subject)
    db.commit()
    return _to_out(subject, {})


@router.get("/{subject_id}", response_model=SubjectOut)
def get_subject(subject_id: IdPath, db: Session = Depends(get_db)) -> SubjectOut:
    # 200 Subject+계산필드 / 404 not_found
    subject = get_subject_or_404(db, subject_id)
    return _to_out(subject, _stats(db, subject_id))


@router.patch("/{subject_id}", response_model=SubjectOut)
def update_subject(
    payload: SubjectUpdate, subject_id: IdPath, db: Session = Depends(get_db)
) -> SubjectOut:
    # 보낸 필드만 수정. 200 / 404 / 422
    subject = get_subject_or_404(db, subject_id)
    changes = payload.model_dump(exclude_unset=True)
    if "started_on" in changes or "target_date" in changes:
        # F12: 보낸 값과 저장된 값을 합쳐 검사한다. 둘 다 안 보내면 이 규칙 전의 값도 그대로 둔다.
        _check_date_order(
            changes.get("started_on", subject.started_on),
            changes.get("target_date", subject.target_date),
        )
    for field, value in changes.items():
        setattr(subject, field, value)
    db.commit()
    return _to_out(subject, _stats(db, subject_id))
