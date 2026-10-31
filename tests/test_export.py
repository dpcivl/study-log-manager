"""F6 마크다운 내보내기 계약 테스트.

완료 기준
- 내보내기 버튼을 누르면 `<주제이름>.md` 파일이 내려받히고, 공부 기록은 "- 10월 26일: 1h"
  형식으로, 노트는 유형별 섹션 아래 "## 제목" + 본문으로 들어 있다.

해석
- 본문은 `# 베이스`, `# 기간`, `# 공부 기록`, `# 기억할 것`, `# 디버깅`, `# 후기` 여섯 제목이
  이 순서로 나온다. 비어 있어도 제목은 남는다.
- 공부 기록은 한 건당 한 줄이고 날짜 오름차순, 같은 날은 id 오름차순이다.
- 시간 표기는 화면의 formatHours와 같다. 분/60을 소수 첫째 자리로 반올림(.5는 올림)하고,
  정수면 소수점 없이 "1h", 아니면 "1.5h"로 쓴다.
- 노트는 유형별 섹션 안에서 생성 오름차순(같은 시각이면 id 오름차순)이다.
  "## 제목", 미해결이면 "## 제목 (미해결)". 태그가 있으면 "태그: a, b" 줄과 빈 줄 뒤에 본문,
  태그가 없으면 "태그:" 줄이 없다. 본문은 한 글자도 바꾸지 않는다.
- 파일 이름은 주제 이름에서 `/`, `\\`, `..`를 지운 값이고, 지우고 나서 비면 `subject`다.
  `Content-Disposition`은 `filename*=UTF-8''` 인코딩만 쓴다.
- API 경로의 id가 정수가 아니거나 범위 밖이면 없는 자원으로 보고 404다.
"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

HEADERS = ["# 베이스", "# 기간", "# 공부 기록", "# 기억할 것", "# 디버깅", "# 후기"]
KIND_HEADER = {
    "remember": "# 기억할 것",
    "debug": "# 디버깅",
    "review": "# 후기",
}
BAD_IDS = ["abc", "0", "-1", str(2**63), str(2**64)]

SUBJECT_NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "주제를 찾을 수 없습니다"},
}
UNAUTHORIZED_BODY = {
    "error": {"code": "unauthorized", "message": "로그인이 필요합니다"},
}


# ---------- 헬퍼 ----------


def make_subject(
    client: TestClient,
    name: str = "테스트 주제",
    background: str = "",
    started_on: str = "2026-10-26",
    target_date: str | None = None,
) -> int:
    response = client.post(
        "/api/subjects",
        json={
            "name": name,
            "background": background,
            "started_on": started_on,
            "target_date": target_date,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_session(
    client: TestClient,
    subject_id: int,
    studied_on: str,
    minutes: int,
    memo: str = "",
) -> int:
    response = client.post(
        f"/api/subjects/{subject_id}/sessions",
        json={"studied_on": studied_on, "minutes": minutes, "memo": memo},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_note(
    client: TestClient,
    subject_id: int,
    kind: str,
    title: str,
    body: str = "",
    tags: list[str] | None = None,
    is_open: bool = False,
) -> int:
    response = client.post(
        f"/api/subjects/{subject_id}/notes",
        json={
            "kind": kind,
            "title": title,
            "body": body,
            "tags": tags or [],
            "is_open": is_open,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def export(client: TestClient, subject_id: int | str):
    return client.get(f"/api/subjects/{subject_id}/export")


def export_text(client: TestClient, subject_id: int) -> str:
    response = export(client, subject_id)
    assert response.status_code == 200, response.text
    return response.text


def sections(text: str) -> dict[str, list[str]]:
    """여섯 최상위 제목 기준으로 본문 줄(빈 줄 포함)을 나눈다."""
    result: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.split("\n"):
        if line in HEADERS and line not in result:
            current = []
            result[line] = current
        elif current is not None:
            current.append(line)
    return result


def nonblank(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip()]


def disposition(name: str) -> str:
    return "attachment; filename*=UTF-8''" + quote(name + ".md")


# ---------- 섹션 순서와 빈 주제 ----------


def test_f6_six_headings_appear_in_promised_order(auth_client: TestClient):
    sid = make_subject(auth_client, background="베이스 내용")
    add_session(auth_client, sid, "2026-10-26", 60)
    add_note(auth_client, sid, "review", "후기 노트")
    add_note(auth_client, sid, "debug", "디버깅 노트")
    add_note(auth_client, sid, "remember", "기억 노트")

    text = export_text(auth_client, sid)
    lines = text.split("\n")
    positions = [lines.index(h) for h in HEADERS]

    assert positions == sorted(positions)
    assert len(set(positions)) == 6
    assert text.startswith("# 베이스\n")


def test_f6_empty_subject_still_has_all_six_headings(auth_client: TestClient):
    sid = make_subject(auth_client, background="")

    secs = sections(export_text(auth_client, sid))

    assert list(secs) == HEADERS
    assert nonblank(secs["# 공부 기록"]) == []
    assert nonblank(secs["# 기억할 것"]) == []
    assert nonblank(secs["# 디버깅"]) == []
    assert nonblank(secs["# 후기"]) == []
    assert nonblank(secs["# 베이스"]) == []


def test_f6_kinds_without_notes_keep_their_heading(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "debug", "디버깅만 있음")

    secs = sections(export_text(auth_client, sid))

    assert list(secs) == HEADERS
    assert nonblank(secs["# 기억할 것"]) == []
    assert nonblank(secs["# 디버깅"]) == ["## 디버깅만 있음"]
    assert nonblank(secs["# 후기"]) == []


# ---------- 베이스·기간 ----------


def test_f6_base_section_has_background(auth_client: TestClient):
    background = "임베디드 HW 개발 1년 / SW 개발 2년 5개월 / 정보처리산업기사"
    sid = make_subject(auth_client, background=background)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 베이스"]) == [background]


def test_f6_multiline_background_is_kept(auth_client: TestClient):
    sid = make_subject(auth_client, background="첫째 줄\n둘째 줄\n\n넷째 줄")

    secs = sections(export_text(auth_client, sid))

    assert "\n".join(secs["# 베이스"]).strip("\n") == "첫째 줄\n둘째 줄\n\n넷째 줄"


def test_f6_period_section_has_start_and_target(auth_client: TestClient):
    sid = make_subject(auth_client, started_on="2026-10-26", target_date="2026-12-06")

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기간"]) == ["- 시작: 2026-10-26", "- 목표: 2026-12-06"]


def test_f6_period_without_target_says_none(auth_client: TestClient):
    sid = make_subject(auth_client, started_on="2026-10-26", target_date=None)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기간"]) == ["- 시작: 2026-10-26", "- 목표: (없음)"]


def test_f6_period_reflects_patched_subject(auth_client: TestClient):
    sid = make_subject(auth_client, started_on="2026-10-26")
    response = auth_client.patch(
        f"/api/subjects/{sid}",
        json={"target_date": "2026-12-06", "background": "수정한 배경"},
    )
    assert response.status_code == 200, response.text

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기간"]) == ["- 시작: 2026-10-26", "- 목표: 2026-12-06"]
    assert nonblank(secs["# 베이스"]) == ["수정한 배경"]


# ---------- 공부 기록 ----------


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (60, "1h"),
        (120, "2h"),
        (90, "1.5h"),
        (30, "0.5h"),
        (45, "0.8h"),
        (15, "0.3h"),
        (3, "0.1h"),
        (1, "0h"),
        (100, "1.7h"),
        (1440, "24h"),
    ],
)
def test_f6_time_format(auth_client: TestClient, minutes: int, expected: str):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, "2026-01-05", minutes)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == [f"- 1월 5일: {expected}"]


@pytest.mark.parametrize(
    ("studied_on", "expected"),
    [
        ("2026-01-05", "- 1월 5일: 1h"),
        ("2026-10-06", "- 10월 6일: 1h"),
        ("2026-11-10", "- 11월 10일: 1h"),
        ("2026-12-31", "- 12월 31일: 1h"),
        ("2026-02-01", "- 2월 1일: 1h"),
    ],
)
def test_f6_date_has_no_leading_zero(auth_client: TestClient, studied_on: str, expected: str):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, studied_on, 60)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == [expected]


def test_f6_sessions_are_in_ascending_date_order(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, "2026-10-29", 120)
    add_session(auth_client, sid, "2026-10-26", 60)
    add_session(auth_client, sid, "2026-10-28", 90)
    add_session(auth_client, sid, "2026-10-27", 30)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == [
        "- 10월 26일: 1h",
        "- 10월 27일: 0.5h",
        "- 10월 28일: 1.5h",
        "- 10월 29일: 2h",
    ]


def test_f6_sessions_sort_by_date_across_years(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, "2026-01-01", 120)
    add_session(auth_client, sid, "2025-12-31", 60)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == ["- 12월 31일: 1h", "- 1월 1일: 2h"]


def test_f6_same_day_sessions_are_two_lines_in_id_order(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, "2026-10-26", 120)
    add_session(auth_client, sid, "2026-10-26", 30)
    add_session(auth_client, sid, "2026-10-25", 60)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == [
        "- 10월 25일: 1h",
        "- 10월 26일: 2h",
        "- 10월 26일: 0.5h",
    ]


def test_f6_session_with_memo_keeps_one_line_starting_with_date_and_hours(
    auth_client: TestClient,
):
    sid = make_subject(auth_client)
    add_session(auth_client, sid, "2026-10-26", 60, memo="시나공 ch3")

    lines = nonblank(sections(export_text(auth_client, sid))["# 공부 기록"])

    assert len(lines) == 1
    assert lines[0].startswith("- 10월 26일: 1h")


def test_f6_session_edit_and_delete_are_reflected(auth_client: TestClient):
    sid = make_subject(auth_client)
    keep = add_session(auth_client, sid, "2026-10-26", 60)
    gone = add_session(auth_client, sid, "2026-10-27", 60)
    assert auth_client.patch(f"/api/sessions/{keep}", json={"minutes": 90}).status_code == 200
    assert auth_client.delete(f"/api/sessions/{gone}").status_code == 204

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 공부 기록"]) == ["- 10월 26일: 1.5h"]


# ---------- 노트 ----------


def test_f6_notes_go_under_their_kind_section(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "review", "후기 하나")
    add_note(auth_client, sid, "debug", "디버깅 하나")
    add_note(auth_client, sid, "remember", "기억 하나")

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs[KIND_HEADER["remember"]]) == ["## 기억 하나"]
    assert nonblank(secs[KIND_HEADER["debug"]]) == ["## 디버깅 하나"]
    assert nonblank(secs[KIND_HEADER["review"]]) == ["## 후기 하나"]


def test_f6_notes_in_a_section_are_in_creation_order(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "remember", "첫째")
    add_note(auth_client, sid, "debug", "디버깅")
    add_note(auth_client, sid, "remember", "둘째")
    add_note(auth_client, sid, "remember", "셋째")

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기억할 것"]) == ["## 첫째", "## 둘째", "## 셋째"]
    assert nonblank(secs["# 디버깅"]) == ["## 디버깅"]


def test_f6_creation_order_ignores_later_edits(auth_client: TestClient):
    sid = make_subject(auth_client)
    first = add_note(auth_client, sid, "remember", "먼저 만든 노트")
    add_note(auth_client, sid, "remember", "나중에 만든 노트")
    response = auth_client.patch(f"/api/notes/{first}", json={"body": "수정함"})
    assert response.status_code == 200, response.text

    secs = sections(export_text(auth_client, sid))

    titles = [line for line in secs["# 기억할 것"] if line.startswith("## ")]
    assert titles == ["## 먼저 만든 노트", "## 나중에 만든 노트"]


def test_f6_open_note_title_gets_unresolved_suffix(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "remember", "답을 모름", is_open=True)
    add_note(auth_client, sid, "remember", "답을 앎", is_open=False)

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기억할 것"]) == ["## 답을 모름 (미해결)", "## 답을 앎"]


def test_f6_resolved_note_loses_unresolved_suffix(auth_client: TestClient):
    sid = make_subject(auth_client)
    nid = add_note(auth_client, sid, "remember", "질문", is_open=True)
    assert auth_client.patch(f"/api/notes/{nid}", json={"is_open": False}).status_code == 200

    secs = sections(export_text(auth_client, sid))

    assert nonblank(secs["# 기억할 것"]) == ["## 질문"]


def test_f6_note_with_tags_has_tag_line_then_blank_then_body(
    auth_client: TestClient,
):
    sid = make_subject(auth_client)
    add_note(
        auth_client,
        sid,
        "remember",
        "csv 저장 시 인덱스 제외",
        body="인덱스를 제외하고 저장하려면 index=False",
        tags=["pandas", "csv"],
    )

    lines = sections(export_text(auth_client, sid))["# 기억할 것"]
    at = lines.index("## csv 저장 시 인덱스 제외")

    assert lines[at + 1] == "태그: pandas, csv"
    assert lines[at + 2] == ""
    assert lines[at + 3] == "인덱스를 제외하고 저장하려면 index=False"


def test_f6_note_with_single_tag(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "debug", "에러", body="내용", tags=["pandas"])

    lines = sections(export_text(auth_client, sid))["# 디버깅"]
    at = lines.index("## 에러")

    assert lines[at + 1] == "태그: pandas"
    assert lines[at + 2] == ""
    assert lines[at + 3] == "내용"


def test_f6_note_without_tags_has_no_tag_line(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "review", "코딩팡 사용", body="재밌었다", tags=[])

    lines = sections(export_text(auth_client, sid))["# 후기"]

    assert not any(line.startswith("태그:") for line in lines)
    assert nonblank(lines) == ["## 코딩팡 사용", "재밌었다"]


def test_f6_note_with_empty_body_has_no_body_lines(auth_client: TestClient):
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "remember", "본문 없음", body="", tags=[])
    add_note(auth_client, sid, "remember", "태그만 있음", body="", tags=["a", "b"])

    lines = sections(export_text(auth_client, sid))["# 기억할 것"]

    assert nonblank(lines) == ["## 본문 없음", "## 태그만 있음", "태그: a, b"]


def test_f6_note_body_is_kept_as_is(auth_client: TestClient):
    body = (
        "인덱스를 제외하고 저장하려면 index=False\n\n"
        "```python\ndf.to_csv('cafe.csv', index=False)\n```\n\n"
        "- 목록 *강조* `코드`\n> 인용"
    )
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "remember", "본문 보존", body=body, tags=["csv"])

    text = export_text(auth_client, sid)

    assert body in text


def test_f6_note_body_with_many_blank_lines_in_code_block_is_kept(
    auth_client: TestClient,
):
    body = "```python\nimport pandas as pd\n\n\n\n\nprint(pd.__version__)\n```"
    sid = make_subject(auth_client)
    add_note(auth_client, sid, "debug", "빈 줄이 많은 코드", body=body)

    text = export_text(auth_client, sid)

    assert body in text
    assert "import pandas as pd\n\n\n\n\nprint(pd.__version__)" in text


def test_f6_korean_text_is_not_garbled(auth_client: TestClient):
    sid = make_subject(
        auth_client, name="빅데이터분석기사 실기", background="한글 배경: 가나다라마바사"
    )
    add_note(
        auth_client,
        sid,
        "review",
        "코딩팡 사용",
        body="한글 본문입니다. 😀 이모지도 그대로",
        tags=["한글태그"],
    )

    response = export(auth_client, sid)
    text = response.content.decode("utf-8")

    assert "한글 배경: 가나다라마바사" in text
    assert "## 코딩팡 사용" in text
    assert "태그: 한글태그" in text
    assert "한글 본문입니다. 😀 이모지도 그대로" in text


def test_f6_other_subjects_data_is_not_mixed_in(auth_client: TestClient):
    mine = make_subject(auth_client, name="내 주제", background="내 배경")
    other = make_subject(auth_client, name="다른 주제", background="다른 배경")
    add_session(auth_client, mine, "2026-10-26", 60)
    add_session(auth_client, other, "2026-10-27", 120)
    add_note(auth_client, mine, "remember", "내 노트", body="내 본문")
    add_note(auth_client, other, "remember", "다른 노트", body="다른 본문")
    add_note(auth_client, other, "debug", "다른 디버깅")

    secs = sections(export_text(auth_client, mine))

    assert nonblank(secs["# 베이스"]) == ["내 배경"]
    assert nonblank(secs["# 공부 기록"]) == ["- 10월 26일: 1h"]
    assert nonblank(secs["# 기억할 것"]) == ["## 내 노트", "내 본문"]
    assert nonblank(secs["# 디버깅"]) == []


# ---------- 설계 본문 예시 ----------


def test_f6_design_example_shape(auth_client: TestClient):
    background = "임베디드 HW 개발 1년 / SW 개발 2년 5개월 / 정보처리산업기사 / AI 엔지니어 1개월째"
    sid = make_subject(
        auth_client,
        name="빅데이터분석기사 실기",
        background=background,
        started_on="2026-10-26",
        target_date=None,
    )
    add_session(auth_client, sid, "2026-10-27", 120)
    add_session(auth_client, sid, "2026-10-26", 60)
    add_note(
        auth_client,
        sid,
        "review",
        "코딩팡 사용",
        body="후기 본문",
    )
    add_note(
        auth_client,
        sid,
        "debug",
        "FileNotFoundError: temp_csv",
        body="경로를 확인했다",
    )
    add_note(
        auth_client,
        sid,
        "remember",
        "csv 저장 시 인덱스 제외",
        body="인덱스를 제외하고 저장하려면 index=False",
        tags=["pandas", "csv"],
    )

    text = export_text(auth_client, sid)

    assert text.startswith("# 베이스\n" + background + "\n")
    assert nonblank(text.split("\n")) == [
        "# 베이스",
        background,
        "# 기간",
        "- 시작: 2026-10-26",
        "- 목표: (없음)",
        "# 공부 기록",
        "- 10월 26일: 1h",
        "- 10월 27일: 2h",
        "# 기억할 것",
        "## csv 저장 시 인덱스 제외",
        "태그: pandas, csv",
        "인덱스를 제외하고 저장하려면 index=False",
        "# 디버깅",
        "## FileNotFoundError: temp_csv",
        "경로를 확인했다",
        "# 후기",
        "## 코딩팡 사용",
        "후기 본문",
    ]


# ---------- 응답 헤더 ----------


def test_f6_content_type_is_markdown_utf8(auth_client: TestClient):
    sid = make_subject(auth_client)

    response = export(auth_client, sid)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"


def test_f6_content_disposition_for_ascii_name(auth_client: TestClient):
    sid = make_subject(auth_client, name="python")

    response = export(auth_client, sid)

    assert response.headers["content-disposition"] == ("attachment; filename*=UTF-8''python.md")


def test_f6_content_disposition_for_korean_name(auth_client: TestClient):
    name = "빅데이터분석기사 실기"
    sid = make_subject(auth_client, name=name)

    response = export(auth_client, sid)

    assert response.headers["content-disposition"] == disposition(name)
    assert response.headers["content-disposition"].endswith(".md")
    assert "%EB%B9%85" in response.headers["content-disposition"]


def test_f6_content_disposition_for_name_with_spaces(auth_client: TestClient):
    name = "my study log"
    sid = make_subject(auth_client, name=name)

    response = export(auth_client, sid)

    assert response.headers["content-disposition"] == disposition(name)
    assert " " not in response.headers["content-disposition"].split("''", 1)[1]


def test_f6_content_disposition_uses_only_extended_filename(
    auth_client: TestClient,
):
    sid = make_subject(auth_client, name="한글 이름")

    value = export(auth_client, sid).headers["content-disposition"]

    assert value.startswith("attachment; filename*=UTF-8''")
    assert 'filename="' not in value
    assert "; filename=" not in value


# ---------- 파일 이름 정리 ----------


@pytest.mark.parametrize(
    ("name", "filename"),
    [
        ("a/b", "ab"),
        ("a\\b", "ab"),
        ("../x", "x"),
        ("..\\x", "x"),
        ("../../etc/passwd", "etcpasswd"),
        ("a/../b", "ab"),
        ("..foo", "foo"),
        ("x..", "x"),
        ("a..b", "ab"),
    ],
)
def test_f6_path_characters_are_removed_from_filename(
    auth_client: TestClient, name: str, filename: str
):
    sid = make_subject(auth_client, name=name)

    response = export(auth_client, sid)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == disposition(filename)


@pytest.mark.parametrize("name", ["..", "....", "/", "\\", "/..\\"])
def test_f6_name_that_becomes_empty_falls_back_to_subject(auth_client: TestClient, name: str):
    sid = make_subject(auth_client, name=name)

    response = export(auth_client, sid)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == disposition("subject")


def test_f6_filename_has_no_path_separator_or_dotdot(auth_client: TestClient):
    sid = make_subject(auth_client, name="a/b\\c..d/../e")

    value = export(auth_client, sid).headers["content-disposition"]
    filename = value.split("''", 1)[1]

    assert "/" not in filename
    assert "\\" not in filename
    assert "%2F" not in filename.upper()
    assert "%5C" not in filename.upper()
    assert ".." not in filename


def test_f6_name_with_newline_is_rejected_at_creation(auth_client: TestClient):
    # SEC-5: 이름 같은 한 줄 필드는 제어 문자를 거부하므로 줄바꿈 든 이름은 만들어지지 않는다.
    # 따라서 Content-Disposition에 줄바꿈이 들어갈 이름이 새로 저장되지 않는다.
    response = auth_client.post(
        "/api/subjects",
        json={"name": "줄\n바꿈", "background": "", "started_on": "2026-10-26"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "name" in response.json()["error"]["fields"]
    assert auth_client.get("/api/subjects").json()["items"] == []


def test_f6_name_with_double_quote_does_not_break_response(
    auth_client: TestClient,
):
    name = 'say "hi"'
    sid = make_subject(auth_client, name=name)

    response = export(auth_client, sid)

    assert response.status_code == 200
    value = response.headers["content-disposition"]
    assert '"' not in value
    assert value == disposition(name)


def test_f6_export_does_not_change_subject_name(auth_client: TestClient):
    name = "../원본 이름"
    sid = make_subject(auth_client, name=name)
    export(auth_client, sid)

    assert auth_client.get(f"/api/subjects/{sid}").json()["name"] == name


# ---------- 오류 ----------


def test_f6_unknown_subject_returns_404(auth_client: TestClient):
    response = export(auth_client, 9999)

    assert response.status_code == 404
    assert response.json() == SUBJECT_NOT_FOUND_BODY


def test_f6_error_message_says_subject_not_found(auth_client: TestClient):
    response = export(auth_client, 424242)

    assert "주제를 찾을 수 없습니다" in response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f6_invalid_id_returns_404(auth_client: TestClient, bad_id: str):
    response = export(auth_client, bad_id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_f6_requires_login(client: TestClient):
    response = export(client, 1)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_f6_requires_login_even_for_existing_subject(
    auth_client: TestClient,
):
    sid = make_subject(auth_client, name="로그인 필요")
    assert auth_client.post("/api/logout").status_code == 204

    response = export(auth_client, sid)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY
    assert "로그인 필요" not in response.text
