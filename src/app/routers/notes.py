"""F3 /api/subjects/{id}/notes(POST), /api/notes/{id} / F4 /api/subjects/{id}/notes(GET)"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.errors import NotImplementedAPIError
from app.schemas import NoteCreate, NoteKind, NoteList, NoteOut, NoteUpdate

router = APIRouter(prefix="/api", tags=["F3", "F4"], dependencies=[Depends(require_session)])


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
def create_note(subject_id: int, payload: NoteCreate, db: Session = Depends(get_db)) -> NoteOut:
    # F3: 201 Note / 404 / 422
    raise NotImplementedAPIError()


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)) -> NoteOut:
    # F3: 200 Note / 404
    raise NotImplementedAPIError()


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db)) -> NoteOut:
    # F3: 200 Note(updated_at 갱신) / 404 / 422
    raise NotImplementedAPIError()


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: Session = Depends(get_db)) -> None:
    # F3: 204 / 404
    raise NotImplementedAPIError()
