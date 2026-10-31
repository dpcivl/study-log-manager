"""Pydantic 요청·응답 모델. design.md 4절 제한값과 5절 응답 모양을 그대로 옮겼다."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

NoteKind = Literal["remember", "debug", "review"]


def _iso_utc(value: datetime) -> str:
    """ISO 8601 UTC. 예: 2026-10-31T11:20:00Z"""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class _OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- F5 인증 ----
class LoginRequest(BaseModel):
    password: str


# ---- F1 Subject ----
def _not_blank(value: str) -> str:
    """공백만 있는 이름은 비어 있는 것으로 본다. 통과한 값은 받은 그대로 저장한다."""
    if not value.strip():
        raise ValueError("이름이 비어 있습니다")
    return value


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_date_only(value: object) -> object:
    """날짜는 "YYYY-MM-DD" 문자열만 받는다(숫자 타임스탬프, 날짜+시각 문자열은 거부)."""
    if value is None or (isinstance(value, str) and _ISO_DATE.fullmatch(value)):
        return value
    raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    background: str = Field(default="", max_length=5000)
    started_on: date
    target_date: date | None = None

    _check_name = field_validator("name")(_not_blank)
    _check_dates = field_validator("started_on", "target_date", mode="before")(_iso_date_only)


class SubjectUpdate(BaseModel):
    # 보낸 필드만 수정한다(exclude_unset). name·background·started_on은 null을 허용하지 않아
    # 기본값을 None으로 두되 타입은 non-null로 선언한다(null을 보내면 422, 생략하면 변경 없음).
    # target_date는 null을 보내면 목표일을 지운다.
    name: str = Field(default=None, min_length=1, max_length=100)
    background: str = Field(default=None, max_length=5000)
    started_on: date = Field(default=None)
    target_date: date | None = None

    _check_name = field_validator("name")(_not_blank)
    _check_dates = field_validator("started_on", "target_date", mode="before")(_iso_date_only)


class SubjectOut(_OutModel):
    id: int
    name: str
    background: str
    started_on: date
    target_date: date | None
    created_at: datetime
    updated_at: datetime
    # 응답에만 붙는 계산 필드
    total_minutes: int = 0
    last7_minutes: int = 0
    days_studied: int = 0
    note_count: int = 0
    open_note_count: int = 0

    @field_serializer("created_at", "updated_at")
    def _ser_dt(self, value: datetime) -> str:
        return _iso_utc(value)


class SubjectList(BaseModel):
    items: list[SubjectOut]


# ---- F2 StudySession ----
class StudySessionCreate(BaseModel):
    studied_on: date
    # 정수만 받는다(60.5, "60", true는 422). 15 단위는 화면 입력 편의일 뿐이다.
    minutes: int = Field(strict=True, ge=1, le=1440)
    memo: str = Field(default="", max_length=500)

    _check_date = field_validator("studied_on", mode="before")(_iso_date_only)


class StudySessionUpdate(BaseModel):
    # 보낸 필드만 수정한다(exclude_unset). 세 필드 모두 null을 허용하지 않아
    # 기본값을 None으로 두되 타입은 non-null로 선언한다(null을 보내면 422, 생략하면 변경 없음).
    studied_on: date = Field(default=None)
    minutes: int = Field(default=None, strict=True, ge=1, le=1440)
    memo: str = Field(default=None, max_length=500)

    _check_date = field_validator("studied_on", mode="before")(_iso_date_only)


class StudySessionOut(_OutModel):
    id: int
    subject_id: int
    studied_on: date
    minutes: int
    memo: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_dt(self, value: datetime) -> str:
        return _iso_utc(value)


class StudySessionList(BaseModel):
    items: list[StudySessionOut]
    total: int
    page: int
    limit: int
    total_minutes: int


# ---- F3 / F4 Note ----
MAX_TAGS = 20
MAX_TAG_LENGTH = 30


def _clean_tags(tags: list[str]) -> list[str]:
    """태그를 앞뒤 공백 제거·소문자로 정리하고 중복은 처음 하나만 남긴다(순서 유지).

    개수(최대 20)와 길이(각 1..30자)는 정리를 마친 값으로 검사한다.
    """
    cleaned: list[str] = []
    for tag in tags:
        try:
            # JSON의 짝 없는 서로게이트("\ud800")는 UTF-8로 저장·응답할 수 없다.
            tag.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("태그에 사용할 수 없는 문자가 있습니다") from None
        tag = tag.strip().lower()
        if not 1 <= len(tag) <= MAX_TAG_LENGTH:
            raise ValueError("태그는 각 1~30자여야 합니다")
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise ValueError("태그는 최대 20개입니다")
    return cleaned


def _title_not_blank(value: str) -> str:
    """공백만 있는 제목은 비어 있는 것으로 본다. 통과한 값은 받은 그대로 저장한다."""
    if not value.strip():
        raise ValueError("제목이 비어 있습니다")
    return value


class NoteCreate(BaseModel):
    kind: NoteKind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list)
    is_open: bool = Field(default=False, strict=True)

    _check_title = field_validator("title")(_title_not_blank)
    _check_tags = field_validator("tags")(_clean_tags)


class NoteUpdate(BaseModel):
    # 보낸 필드만 수정한다(exclude_unset). 다섯 필드 모두 null을 허용하지 않아 기본값을 None으로
    # 두되 타입은 non-null로 선언한다(null을 보내면 422, 생략하면 변경 없음).
    kind: NoteKind = Field(default=None)
    title: str = Field(default=None, min_length=1, max_length=200)
    body: str = Field(default=None, max_length=50000)
    tags: list[str] = Field(default=None)
    is_open: bool = Field(default=None, strict=True)

    _check_title = field_validator("title")(_title_not_blank)
    _check_tags = field_validator("tags")(_clean_tags)


class NoteOut(_OutModel):
    id: int
    subject_id: int
    kind: NoteKind
    title: str
    body: str
    tags: list[str]
    is_open: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _ser_dt(self, value: datetime) -> str:
        return _iso_utc(value)


class NoteList(BaseModel):
    items: list[NoteOut]
    total: int
    page: int
    limit: int
    tags: list[str]  # 이 주제 노트의 모든 태그(중복 제거, 가나다·알파벳순)


# ---- 공통 오류 ----
class ErrorBody(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None
    retry_after: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
