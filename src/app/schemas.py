"""Pydantic 요청·응답 모델. design.md 4절 제한값과 5절 응답 모양을 그대로 옮겼다."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

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
class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    background: str = Field(default="", max_length=5000)
    started_on: date
    target_date: date | None = None


class SubjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    background: str | None = Field(default=None, max_length=5000)
    started_on: date | None = None
    target_date: date | None = None


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
    minutes: int = Field(ge=1, le=1440)
    memo: str = Field(default="", max_length=500)


class StudySessionUpdate(BaseModel):
    studied_on: date | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    memo: str | None = Field(default=None, max_length=500)


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
class NoteCreate(BaseModel):
    kind: NoteKind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_open: bool = False


class NoteUpdate(BaseModel):
    kind: NoteKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=20)
    is_open: bool | None = None


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
