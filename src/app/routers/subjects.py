"""F1 /api/subjects"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.errors import NotImplementedAPIError
from app.schemas import SubjectCreate, SubjectList, SubjectOut, SubjectUpdate

router = APIRouter(prefix="/api/subjects", tags=["F1"], dependencies=[Depends(require_session)])


@router.get("", response_model=SubjectList)
def list_subjects(db: Session = Depends(get_db)) -> SubjectList:
    # 200 {items:[Subject+계산필드]} 생성 최신순
    raise NotImplementedAPIError()


@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)) -> SubjectOut:
    # 201 Subject+계산필드 / 422 validation_error
    raise NotImplementedAPIError()


@router.get("/{subject_id}", response_model=SubjectOut)
def get_subject(subject_id: int, db: Session = Depends(get_db)) -> SubjectOut:
    # 200 Subject+계산필드 / 404 not_found
    raise NotImplementedAPIError()


@router.patch("/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int, payload: SubjectUpdate, db: Session = Depends(get_db)
) -> SubjectOut:
    # 보낸 필드만 수정. 200 / 404 / 422
    raise NotImplementedAPIError()
