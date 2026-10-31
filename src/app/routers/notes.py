"""F3 /api/subjects/{id}/notes(POST), /api/notes/{id} / F4 /api/subjects/{id}/notes(GET)"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.deps import IdPath, get_subject_or_404
from app.errors import NotImplementedAPIError, not_found
from app.models import Note, utcnow
from app.schemas import NoteCreate, NoteKind, NoteList, NoteOut, NoteUpdate

router = APIRouter(prefix="/api", tags=["F3", "F4"], dependencies=[Depends(require_session)])


def _get_note_or_404(db: Session, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise not_found("note_id")
    return note


@router.get("/subjects/{subject_id}/notes", response_model=NoteList)
def list_notes(
    subject_id: int,
    kind: NoteKind | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    q: str | None = Query(default=None),
    open: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> NoteList:
    # F4: 200 목록(updated_at desc) + tags(이 주제의 태그 전부) / 404 / 422(kind가 세 값 밖)
    raise NotImplementedAPIError()


@router.post(
    "/subjects/{subject_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED
)
def create_note(payload: NoteCreate, subject_id: IdPath, db: Session = Depends(get_db)) -> NoteOut:
    # F3: 201 Note / 404 / 422
    get_subject_or_404(db, subject_id)
    note = Note(
        subject_id=subject_id,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        tags=payload.tags,
        is_open=payload.is_open,
    )
    db.add(note)
    db.commit()
    return NoteOut.model_validate(note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: IdPath, db: Session = Depends(get_db)) -> NoteOut:
    # F3: 200 Note / 404
    return NoteOut.model_validate(_get_note_or_404(db, note_id))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(payload: NoteUpdate, note_id: IdPath, db: Session = Depends(get_db)) -> NoteOut:
    # 보낸 필드만 수정. 보낸 필드가 하나라도 있으면 값이 같아도 updated_at을 갱신한다.
    # 빈 객체는 아무것도 바꾸지 않는다. 200 Note / 404 / 422
    note = _get_note_or_404(db, note_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(note, field, value)
    if changes:
        note.updated_at = utcnow()
        db.commit()
    return NoteOut.model_validate(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: IdPath, db: Session = Depends(get_db)) -> Response:
    # F3: 204 / 404
    note = _get_note_or_404(db, note_id)
    db.delete(note)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
