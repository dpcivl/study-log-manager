"""F6 마크다운 내보내기. 주제 하나를 마크다운 글과 파일 이름으로 바꾼다.

라우터와 분리해 두었다. 시드 스크립트가 만든 데이터도 같은 코드로 내보낸다.
"""

import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Note, StudySession, Subject

# 유형 → 섹션 제목. 이 순서대로 내보낸다.
NOTE_SECTIONS = (("remember", "기억할 것"), ("debug", "디버깅"), ("review", "후기"))

NO_TARGET = "(없음)"
OPEN_SUFFIX = " (미해결)"
DEFAULT_NAME = "subject"

_LINE_BREAKS = re.compile(r"[\r\n\u0085  ]+")


def format_hours(minutes: int) -> str:
    """분 → "1.5h". static/js/common.js의 formatHours와 같다.

    JS의 Math.round(minutes / 6) / 10: 소수 첫째 자리까지, .5는 올림, 정수면 소수점 없이.
    정수 계산으로 하면 round-half-even인 Python round()와 달라지는 일이 없다.
    """
    tenths = (minutes + 3) // 6  # floor(minutes / 6 + 0.5)
    whole, frac = divmod(tenths, 10)
    return f"{whole}h" if frac == 0 else f"{whole}.{frac}h"


def export_filename(name: str) -> str:
    """주제 이름 → 내려받을 파일 이름. 경로 문자(/, \\, ..)를 지운다. 비면 subject.md."""
    cleaned = name.replace("/", "").replace("\\", "")
    while ".." in cleaned:  # 지우고 나서 새로 생기는 ..도 지운다
        cleaned = cleaned.replace("..", "")
    return (cleaned.strip() or DEFAULT_NAME) + ".md"


def content_disposition(filename: str) -> str:
    """헤더에 안전한 Content-Disposition 값. 이름은 RFC 5987 퍼센트 인코딩(filename*)만 쓴다."""
    return "attachment; filename*=UTF-8''" + quote(filename, safe="")


def _session_lines(sessions: list[StudySession]) -> list[str]:
    # 한 건당 한 줄. 같은 날 두 건이면 두 줄이다.
    return [
        f"- {s.studied_on.month}월 {s.studied_on.day}일: {format_hours(s.minutes)}"
        for s in sessions
    ]


def _note_text(note: Note) -> str:
    # 제목은 한 줄이어야 제목으로 읽힌다. 본문은 그대로 둔다.
    title = _LINE_BREAKS.sub(" ", note.title).strip()
    lines = ["## " + title + (OPEN_SUFFIX if note.is_open else "")]
    if note.tags:
        lines.append("태그: " + ", ".join(note.tags))
        if note.body:
            lines.append("")
    if note.body:
        lines.append(note.body)
    return "\n".join(lines)


def build_markdown(subject: Subject, sessions: list[StudySession], notes: list[Note]) -> str:
    """sessions는 날짜 오름차순(같은 날은 id 오름차순), notes는 생성 오름차순으로 받는다."""
    blocks = [
        "\n".join(["# 베이스", *([subject.background] if subject.background else [])]),
        "\n".join(
            [
                "# 기간",
                f"- 시작: {subject.started_on.isoformat()}",
                f"- 목표: {subject.target_date.isoformat() if subject.target_date else NO_TARGET}",
            ]
        ),
        "\n".join(["# 공부 기록", *_session_lines(sessions)]),
    ]
    for kind, heading in NOTE_SECTIONS:
        texts = [_note_text(n) for n in notes if n.kind == kind]
        # 제목 바로 아래에 첫 노트, 노트 사이에는 빈 줄 하나
        blocks.append("\n".join([f"# {heading}", "\n\n".join(texts)]) if texts else f"# {heading}")
    return "\n\n".join(blocks) + "\n"


def export_subject_markdown(db: Session, subject: Subject) -> str:
    """DB에서 기록과 노트를 읽어 마크다운 글을 만든다."""
    sessions = list(
        db.scalars(
            select(StudySession)
            .where(StudySession.subject_id == subject.id)
            .order_by(StudySession.studied_on, StudySession.id)
        )
    )
    notes = list(
        db.scalars(
            select(Note).where(Note.subject_id == subject.id).order_by(Note.created_at, Note.id)
        )
    )
    return build_markdown(subject, sessions, notes)
