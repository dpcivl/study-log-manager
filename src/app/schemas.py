"""Pydantic 요청·응답 모델. design.md 4절 제한값과 5절 응답 모양을 그대로 옮겼다."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.errors import CONTROL_MULTI_LINE_MESSAGE, CONTROL_ONE_LINE_MESSAGE, TAG_CHARS_MESSAGE

NoteKind = Literal["remember", "debug", "review"]


def _iso_utc(value: datetime) -> str:
    """ISO 8601 UTC. 예: 2026-10-31T11:20:00Z"""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class _OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- F5 인증 ----
class LoginRequest(BaseModel):
    password: str


# ---- 문자열 공통 검증 ----
# 한 줄 필드(name, title, memo, 태그)는 제어 문자(U+0000~U+001F, U+007F)를 모두 거부한다.
# 여러 줄 필드(background, body)는 줄바꿈(\n, \r)과 탭(\t)만 허용한다.
# 위반하면 422가 되고, 필드 문구는 그 이유를 말하는 errors의 문구를 쓴다.
# password에는 적용하지 않는다.
_CONTROL_ONE_LINE = re.compile(r"[\x00-\x1f\x7f]")
_CONTROL_MULTI_LINE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def has_control_chars(value: str, *, multiline: bool = False) -> bool:
    pattern = _CONTROL_MULTI_LINE if multiline else _CONTROL_ONE_LINE
    return pattern.search(value) is not None


def _single_line(value: str) -> str:
    if has_control_chars(value):
        raise ValueError(CONTROL_ONE_LINE_MESSAGE)
    return value


def _multi_line(value: str) -> str:
    if has_control_chars(value, multiline=True):
        raise ValueError(CONTROL_MULTI_LINE_MESSAGE)
    return value


# ---- F1 Subject ----
def _not_blank(value: str) -> str:
    """공백만 있는 이름은 비어 있는 것으로 본다. 통과한 값은 받은 그대로 저장한다."""
    if not value.strip():
        raise ValueError("이름이 비어 있습니다")
    return value


_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")  # \d는 다른 문자의 숫자도 받는다


def _iso_date_only(value: object) -> object:
    """날짜는 ASCII "YYYY-MM-DD" 문자열만 받는다(숫자 타임스탬프, 날짜+시각 문자열은 거부).

    0000-01-01, 2026-02-30처럼 만들 수 없는 날짜도 여기서 거부한다.
    """
    if value is None:
        return value
    if isinstance(value, str) and (match := _ISO_DATE.fullmatch(value)):
        try:
            date(*map(int, match.groups()))
        except ValueError:
            pass
        else:
            return value
    raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    background: str = Field(default="", max_length=5000)
    started_on: date
    target_date: date | None = None

    _check_name = field_validator("name")(_not_blank)
    _check_name_line = field_validator("name")(_single_line)
    _check_background = field_validator("background")(_multi_line)
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
    _check_name_line = field_validator("name")(_single_line)
    _check_background = field_validator("background")(_multi_line)
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
    _check_memo = field_validator("memo")(_single_line)


class StudySessionUpdate(BaseModel):
    # 보낸 필드만 수정한다(exclude_unset). 세 필드 모두 null을 허용하지 않아
    # 기본값을 None으로 두되 타입은 non-null로 선언한다(null을 보내면 422, 생략하면 변경 없음).
    studied_on: date = Field(default=None)
    minutes: int = Field(default=None, strict=True, ge=1, le=1440)
    memo: str = Field(default=None, max_length=500)

    _check_date = field_validator("studied_on", mode="before")(_iso_date_only)
    _check_memo = field_validator("memo")(_single_line)


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
    seen: set[str] = set()
    for tag in tags:
        # 앞뒤 공백(탭·줄바꿈 포함)을 먼저 지운 뒤, 남은 값 안쪽의 제어 문자와 쉼표를 검사한다.
        tag = tag.strip().lower()
        if has_control_chars(tag) or "," in tag:
            raise ValueError(TAG_CHARS_MESSAGE)
        try:
            # JSON의 짝 없는 서로게이트("\ud800")는 UTF-8로 저장·응답할 수 없다.
            tag.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("태그에 사용할 수 없는 문자가 있습니다") from None
        if not 1 <= len(tag) <= MAX_TAG_LENGTH:
            raise ValueError("태그는 각 1~30자여야 합니다")
        if tag not in seen:
            seen.add(tag)
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
    _check_title_line = field_validator("title")(_single_line)
    _check_body = field_validator("body")(_multi_line)
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
    _check_title_line = field_validator("title")(_single_line)
    _check_body = field_validator("body")(_multi_line)
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
