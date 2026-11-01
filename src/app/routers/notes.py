"""F3 /api/subjects/{id}/notes(POST), /api/notes/{id} / F4 /api/subjects/{id}/notes(GET)"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import exists, func, or_, select, true
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.deps import IdPath, fetch_page, get_subject_or_404
from app.errors import APIError, conflict, not_found
from app.models import Note, utcnow
from app.schemas import NoteCreate, NoteKind, NoteList, NoteOut, NoteUpdate, has_control_chars

router = APIRouter(prefix="/api", tags=["F3", "F4"], dependencies=[Depends(require_session)])


def _get_note_or_404(db: Session, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise not_found("note_id")
    return note


MAX_QUERY_LENGTH = 200
MAX_TAG_FILTERS = 20
MAX_TAG_LENGTH = 30
QUERY_INVALID_MESSAGE = "검색어는 200자 이내여야 합니다"
QUERY_CHARS_MESSAGE = "검색어에 쓸 수 없는 문자가 있습니다"
TAG_FILTER_INVALID_MESSAGE = "태그 조건은 최대 20개, 각 1~30자입니다"
TAG_FILTER_CHARS_MESSAGE = "태그 조건에 쓸 수 없는 문자가 있습니다"


def _validate_filters(tag: list[str] | None, q: str | None) -> str:
    """검색어(앞뒤 공백 제거, 200자 이내, NUL 없음)와 태그 조건(최대 20개, 각 1~30자, 제어 문자·쉼표
    없음)을 검사한다. 벗어나면 422 fields.q / fields.tag. 통과하면 다듬은 검색어를 돌려준다."""
    fields: dict[str, str] = {}
    keyword = (q or "").strip()
    if len(keyword) > MAX_QUERY_LENGTH:
        fields["q"] = QUERY_INVALID_MESSAGE
    elif "\x00" in keyword:
        fields["q"] = QUERY_CHARS_MESSAGE
    if tag:
        if len(tag) > MAX_TAG_FILTERS or any(not 1 <= len(t) <= MAX_TAG_LENGTH for t in tag):
            fields["tag"] = TAG_FILTER_INVALID_MESSAGE
        elif any("," in t or has_control_chars(t) for t in tag):
            fields["tag"] = TAG_FILTER_CHARS_MESSAGE
    if fields:
        raise APIError(422, "validation_error", "입력값을 확인하세요", fields=fields)
    return keyword


def _like_pattern(text: str) -> str:
    """부분 일치용 LIKE 패턴. %, _, \\는 글자 그대로 찾도록 이스케이프한다(escape="\\")."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/subjects/{subject_id}/notes", response_model=NoteList)
def list_notes(
    subject_id: IdPath,
    kind: NoteKind | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    q: str | None = Query(default=None),
    open: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> NoteList:
    # F4: 200 목록(updated_at desc, 같으면 id desc) + tags(이 주제의 태그 전부) / 404 / 422
    keyword = _validate_filters(tag, q)
    get_subject_or_404(db, subject_id)
    conditions = [Note.subject_id == subject_id]
    if kind is not None:
        conditions.append(Note.kind == kind)
    if open:  # open=false나 생략은 조건이 없다
        conditions.append(Note.is_open.is_(True))
    for name in dict.fromkeys(tag or []):  # tags는 JSON 배열: 원소가 정확히 같은 노트만
        tag_values = func.json_each(Note.tags).table_valued("value")
        conditions.append(exists().where(tag_values.c.value == name))
    if keyword:
        pattern = _like_pattern(keyword)
        conditions.append(
            or_(Note.title.like(pattern, escape="\\"), Note.body.like(pattern, escape="\\"))
        )

    total = db.scalar(select(func.count(Note.id)).where(*conditions)) or 0
    items = fetch_page(
        db,
        select(Note).where(*conditions).order_by(Note.updated_at.desc(), Note.id.desc()),
        page,
        limit,
    )
    # 태그 목록은 필터와 무관하게 이 주제 노트 전체에서 모은다.
    all_tags = func.json_each(Note.tags).table_valued("value")
    tag_query = (
        select(all_tags.c.value)
        .select_from(Note)
        .join(all_tags, true())
        .where(Note.subject_id == subject_id)
        .distinct()
    )
    tags = sorted(db.scalars(tag_query))
    return NoteList(
        items=[NoteOut.model_validate(n) for n in items],
        total=int(total),
        page=page,
        limit=limit,
        tags=tags,
    )


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
    # 빈 객체는 아무것도 바꾸지 않는다. 200 Note / 404 / 409 conflict / 422
    # F9: expected_updated_at을 보냈으면 저장된 updated_at(응답과 같은 표기)과 글자 그대로 비교한다.
    # 다르면 아무것도 저장하지 않고 409. 검사 순서는 입력값(422), 없는 노트(404), 충돌(409)이다.
    note = _get_note_or_404(db, note_id)
    if "expected_updated_at" in payload.model_fields_set:
        current = NoteOut.model_validate(note)
        if payload.expected_updated_at != current.model_dump()["updated_at"]:
            raise conflict(current.model_dump())
    changes = payload.model_dump(exclude_unset=True)  # expected_updated_at은 exclude라 빠진다
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
