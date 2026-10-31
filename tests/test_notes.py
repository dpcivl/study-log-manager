"""F3 노트 작성·보기·수정·삭제 계약 테스트.

완료 기준
1. 저장한 노트를 S5에서 열면 마크다운이 렌더되고 ```python 코드 블록이 구문 강조된다.
   (렌더는 브라우저 동작이라 pytest 대상이 아니다. 화면 주소가 로그인 후 200인지,
   마크다운 원문과 코드 블록이 API로 그대로 저장되는지만 확인한다.)
2. 디버깅 유형을 고르고 본문이 비어 있으면
   "## 문제상황 / ## 원인 / ## 해결" 템플릿이 본문에 채워진다.
   (브라우저 동작이라 pytest 대상이 아니다. 서버는 본문을 채우지 않고 받은 그대로 저장한다.)
3. 제목이 비어 있으면 422다.
4. 삭제 확인 후 노트 목록에서 사라지고 GET /api/notes/{id}는 404다.
   (목록 API는 F4라서 삭제 뒤 GET 404와 주제의 note_count, open_note_count 감소로 확인한다.)

해석
- 공백만 있는 제목은 비어 있는 것으로 보고 422다. 그 밖의 제목은 받은 그대로 저장한다.
- 태그는 앞뒤 공백을 지우고 소문자로 바꾼 뒤, 같은 값은 처음 하나만 남긴다(순서 유지).
  1~30자와 최대 20개는 이 정리를 마친 값으로 검사한다. 정리 뒤 빈 태그는 422다.
- PATCH에서 kind, title, body, tags, is_open에 null을 보내면 422다.
- PATCH는 보낸 필드가 하나라도 있으면 updated_at을 갱신한다. 빈 객체 PATCH는 200이고
  아무것도 바꾸지 않는다.
- 없는 노트의 404는 "노트를 찾을 수 없습니다", 없는 주제에 노트를 만들 때의 404는
  "주제를 찾을 수 없습니다"다.
- API 경로의 id가 정수가 아니거나 범위 밖이면 없는 자원으로 보고 404다.
- is_open은 엄격한 불리언이다(문자열·숫자는 422).
"""

import itertools
import re
import time

import pytest
from fastapi.testclient import TestClient

NOTE_KEYS = {
    "id",
    "subject_id",
    "kind",
    "title",
    "body",
    "tags",
    "is_open",
    "created_at",
    "updated_at",
}
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

NOTE_NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "노트를 찾을 수 없습니다"},
}
SUBJECT_NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "주제를 찾을 수 없습니다"},
}
UNSUPPORTED_BODY = {
    "error": {
        "code": "unsupported_media_type",
        "message": "JSON 형식으로 보내야 합니다",
    },
}
VALIDATION_MESSAGE = "입력값을 확인하세요"
KIND_MESSAGE = "remember, debug, review 중 하나여야 합니다"
TITLE_MESSAGE = "제목은 1~200자여야 합니다"
TAGS_MESSAGE = "태그는 최대 20개, 각 1~30자"

BAD_IDS = ["abc", "0", "-1", str(2**63), str(2**64)]

MARKDOWN_BODY = (
    "인덱스를 제외하고 저장하려면 index=False\n"
    "\n"
    "```python\n"
    "df.to_csv('cafe.csv', index=False)\n"
    "```\n"
)


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def create_subject(client: TestClient, name: str = "빅데이터분석기사 실기") -> dict:
    response = client.post(
        "/api/subjects",
        json={"name": name, "background": "", "started_on": "2026-10-26"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def notes_path(subject_id) -> str:
    return f"/api/subjects/{subject_id}/notes"


def note_path(note_id) -> str:
    return f"/api/notes/{note_id}"


def add_note(client: TestClient, subject_id: int, **fields) -> dict:
    payload = {"kind": "remember", "title": "csv 저장 시 인덱스 제외"}
    payload.update(fields)
    response = client.post(notes_path(subject_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def get_note(client: TestClient, note_id: int) -> dict:
    response = client.get(note_path(note_id))
    assert response.status_code == 200, response.text
    return response.json()


def note_counts(client: TestClient, subject_id: int) -> dict:
    """주제 상세와 주제 목록의 노트 개수가 같은지 확인하고 돌려준다."""
    keys = ("note_count", "open_note_count")
    detail = client.get(f"/api/subjects/{subject_id}")
    assert detail.status_code == 200, detail.text
    from_detail = {key: detail.json()[key] for key in keys}

    listing = client.get("/api/subjects")
    assert listing.status_code == 200, listing.text
    matches = [item for item in listing.json()["items"] if item["id"] == subject_id]
    assert len(matches) == 1
    from_list = {key: matches[0][key] for key in keys}

    assert from_list == from_detail
    return from_detail


def assert_counts(client: TestClient, subject_id: int, *, total: int, open_: int) -> None:
    assert note_counts(client, subject_id) == {
        "note_count": total,
        "open_note_count": open_,
    }


def assert_validation_error(response, *field_names: str) -> dict:
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == VALIDATION_MESSAGE
    for name in field_names:
        assert name in error["fields"], error
        assert isinstance(error["fields"][name], str)
        assert error["fields"][name] != ""
    return error


def assert_note_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json() == NOTE_NOT_FOUND_BODY


def assert_subject_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json() == SUBJECT_NOT_FOUND_BODY


# ---------------------------------------------------------------------------
# 생성 (POST /api/subjects/{id}/notes)
# ---------------------------------------------------------------------------


def test_f3_설계_예시_그대로_생성하면_201과_Note_전체가_돌아온다(auth_client):
    subject = create_subject(auth_client)
    payload = {
        "kind": "remember",
        "title": "csv 저장 시 인덱스 제외",
        "body": (
            "인덱스를 제외하고 저장하려면 index=False\n\n"
            "```python\ndf.to_csv('cafe.csv', index=False)\n```"
        ),
        "tags": ["pandas", "csv"],
        "is_open": False,
    }

    response = auth_client.post(notes_path(subject["id"]), json=payload)

    assert response.status_code == 201, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == NOTE_KEYS
    assert isinstance(body["id"], int)
    assert body["subject_id"] == subject["id"]
    for key, value in payload.items():
        assert body[key] == value
    assert DATETIME_RE.match(body["created_at"])
    assert DATETIME_RE.match(body["updated_at"])
    assert body["created_at"] == body["updated_at"]


def test_f3_생성한_노트를_GET으로_그대로_다시_읽는다(auth_client):
    subject = create_subject(auth_client)
    created = add_note(
        auth_client, subject["id"], body=MARKDOWN_BODY, tags=["pandas", "csv"], is_open=True
    )

    response = auth_client.get(note_path(created["id"]))

    assert response.status_code == 200
    assert response.json() == created


def test_f3_body_tags_is_open을_생략하면_기본값이_들어간다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(notes_path(subject["id"]), json={"kind": "review", "title": "후기"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["body"] == ""
    assert body["tags"] == []
    assert body["is_open"] is False


def test_f3_노트마다_다른_id를_받고_각자_주제에_붙는다(auth_client):
    a = create_subject(auth_client, "A")
    b = create_subject(auth_client, "B")

    n1 = add_note(auth_client, a["id"], title="하나")
    n2 = add_note(auth_client, a["id"], title="둘")
    n3 = add_note(auth_client, b["id"], title="셋")

    assert len({n1["id"], n2["id"], n3["id"]}) == 3
    assert get_note(auth_client, n1["id"])["subject_id"] == a["id"]
    assert get_note(auth_client, n3["id"])["subject_id"] == b["id"]


@pytest.mark.parametrize("kind", ["remember", "debug", "review"])
def test_f3_kind_세_값은_모두_저장된다(auth_client, kind):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], kind=kind)

    assert note["kind"] == kind
    assert get_note(auth_client, note["id"])["kind"] == kind


@pytest.mark.parametrize(
    "kind",
    ["", "Remember", "REMEMBER", "memo", "debugging", " debug", 1, True, None, [], {}],
    ids=lambda v: repr(v),
)
def test_f3_kind가_세_값이_아니면_422다(auth_client, kind):
    subject = create_subject(auth_client)

    response = auth_client.post(notes_path(subject["id"]), json={"kind": kind, "title": "제목"})

    error = assert_validation_error(response, "kind")
    assert error["fields"]["kind"] == KIND_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_kind를_빼먹으면_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(notes_path(subject["id"]), json={"title": "제목"})

    error = assert_validation_error(response, "kind")
    assert error["fields"]["kind"] == KIND_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


# --- 제목 (완료 기준 3) ---


def test_f3_제목이_빈_문자열이면_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(notes_path(subject["id"]), json={"kind": "remember", "title": ""})

    error = assert_validation_error(response, "title")
    assert error["fields"]["title"] == TITLE_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


@pytest.mark.parametrize("title", [" ", "   ", "\t", "\n", " \t\n "], ids=lambda v: repr(v))
def test_f3_제목이_공백만_있으면_422다(auth_client, title):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]), json={"kind": "remember", "title": title}
    )

    error = assert_validation_error(response, "title")
    assert error["fields"]["title"] == TITLE_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_제목을_빼먹으면_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(notes_path(subject["id"]), json={"kind": "remember"})

    error = assert_validation_error(response, "title")
    assert error["fields"]["title"] == TITLE_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


@pytest.mark.parametrize("title", [None, 123, True, [], {}, ["a"]], ids=lambda v: repr(v))
def test_f3_제목이_문자열이_아니면_422다(auth_client, title):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]), json={"kind": "remember", "title": title}
    )

    assert_validation_error(response, "title")
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_제목_1자와_200자는_저장된다(auth_client):
    subject = create_subject(auth_client)

    short = add_note(auth_client, subject["id"], title="가")
    longest = add_note(auth_client, subject["id"], title="가" * 200)

    assert short["title"] == "가"
    assert longest["title"] == "가" * 200
    assert get_note(auth_client, longest["id"])["title"] == "가" * 200


def test_f3_제목이_201자이면_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]), json={"kind": "remember", "title": "가" * 201}
    )

    error = assert_validation_error(response, "title")
    assert error["fields"]["title"] == TITLE_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_제목은_받은_그대로_저장한다(auth_client):
    subject = create_subject(auth_client)
    title = "  <b>굵게</b> & \"따옴표\" 'x'  "

    note = add_note(auth_client, subject["id"], title=title)

    assert note["title"] == title
    assert get_note(auth_client, note["id"])["title"] == title


# --- 본문 ---


def test_f3_본문_50000자는_저장되고_50001자는_422다(auth_client):
    subject = create_subject(auth_client)

    ok = add_note(auth_client, subject["id"], body="가" * 50000)
    assert get_note(auth_client, ok["id"])["body"] == "가" * 50000

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "너무 김", "body": "가" * 50001},
    )

    assert_validation_error(response, "body")
    assert_counts(auth_client, subject["id"], total=1, open_=0)


def test_f3_긴_본문의_오류는_fields_body_키로만_나온다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "body": "a" * 50001},
    )

    error = assert_validation_error(response, "body")
    assert set(error["fields"]) == {"body"}
    assert error["code"] == "validation_error"


@pytest.mark.parametrize("body", [None, 123, True, [], {}], ids=lambda v: repr(v))
def test_f3_본문이_문자열이_아니면_422다(auth_client, body):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "body": body},
    )

    assert_validation_error(response, "body")
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_빈_본문은_서버가_채우지_않고_그대로_빈_문자열로_저장한다(auth_client):
    subject = create_subject(auth_client)

    explicit = add_note(auth_client, subject["id"], kind="debug", title="에러", body="")
    omitted = add_note(auth_client, subject["id"], kind="debug", title="에러2")

    assert explicit["body"] == ""
    assert omitted["body"] == ""
    assert get_note(auth_client, explicit["id"])["body"] == ""
    assert get_note(auth_client, omitted["id"])["body"] == ""


def test_f3_디버깅_템플릿_본문도_받은_그대로_저장된다(auth_client):
    subject = create_subject(auth_client)
    template = "## 문제상황\n\n## 원인\n\n## 해결\n"

    note = add_note(
        auth_client, subject["id"], kind="debug", title="FileNotFoundError", body=template
    )

    assert note["body"] == template
    assert get_note(auth_client, note["id"])["body"] == template


def test_f3_마크다운_코드_블록과_줄바꿈이_원문_그대로_저장된다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], body=MARKDOWN_BODY)

    assert note["body"] == MARKDOWN_BODY
    assert get_note(auth_client, note["id"])["body"] == MARKDOWN_BODY
    assert "```python\n" in get_note(auth_client, note["id"])["body"]


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        "# 제목\n\n<img src=x onerror=alert(1)>\n\n[링크](javascript:alert(1))",
        "한글 본문\n\n- 목록 1\n- 목록 2\n\n> 인용\n\n| a | b |\n|---|---|\n| 1 | 2 |",
        "  앞뒤 공백과 빈 줄이 있는 본문  \n\n\n",
        "```python\nprint('a' + \"b\")\nx = {'k': [1, 2]}\n```\n\n```\n코드 2\n```",
        "& &amp; < > \" '",
    ],
    ids=["script", "html-and-js-link", "markdown-ko", "whitespace", "two-code-blocks", "entities"],
)
def test_f3_본문의_특수_문자열을_서버가_바꾸지_않는다(auth_client, body):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], body=body)

    assert note["body"] == body
    assert get_note(auth_client, note["id"])["body"] == body


# --- 태그 ---


def test_f3_태그를_생략하면_빈_배열이다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"])

    assert note["tags"] == []


def test_f3_빈_태그_배열은_빈_배열로_저장된다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], tags=[])

    assert note["tags"] == []
    assert get_note(auth_client, note["id"])["tags"] == []


def test_f3_태그는_앞뒤_공백을_지우고_소문자로_저장한다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], tags=["  Pandas ", "CSV", "\tNumPy\n"])

    assert note["tags"] == ["pandas", "csv", "numpy"]
    assert get_note(auth_client, note["id"])["tags"] == ["pandas", "csv", "numpy"]


def test_f3_정리_뒤_같아지는_태그는_처음_하나만_남기고_순서를_유지한다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(
        auth_client, subject["id"], tags=["Pandas", "csv", " pandas ", "CSV", "numpy", "PANDAS"]
    )

    assert note["tags"] == ["pandas", "csv", "numpy"]
    assert get_note(auth_client, note["id"])["tags"] == ["pandas", "csv", "numpy"]


def test_f3_태그_순서는_보낸_순서를_유지한다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], tags=["z", "a", "m", "b"])

    assert note["tags"] == ["z", "a", "m", "b"]


def test_f3_한글_태그는_그대로_저장된다(auth_client):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], tags=["판다스", " 시각화 "])

    assert note["tags"] == ["판다스", "시각화"]


def test_f3_태그_30자는_저장되고_31자는_422다(auth_client):
    subject = create_subject(auth_client)

    ok = add_note(auth_client, subject["id"], tags=["a" * 30])
    assert ok["tags"] == ["a" * 30]

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": ["a" * 31]},
    )

    error = assert_validation_error(response, "tags")
    assert error["fields"]["tags"] == TAGS_MESSAGE
    assert_counts(auth_client, subject["id"], total=1, open_=0)


def test_f3_태그_길이는_공백을_지운_뒤_기준으로_검사한다(auth_client):
    subject = create_subject(auth_client)

    ok = add_note(auth_client, subject["id"], tags=["  " + "a" * 30 + "  "])

    assert ok["tags"] == ["a" * 30]

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": ["  " + "a" * 31 + "  "]},
    )

    assert_validation_error(response, "tags")


@pytest.mark.parametrize("tag", ["", " ", "   ", "\t", "\n"], ids=lambda v: repr(v))
def test_f3_빈_태그나_공백_태그는_422다(auth_client, tag):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": ["pandas", tag]},
    )

    error = assert_validation_error(response, "tags")
    assert error["fields"]["tags"] == TAGS_MESSAGE
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_태그_20개는_저장되고_21개는_422다(auth_client):
    subject = create_subject(auth_client)
    twenty = [f"tag{i}" for i in range(20)]

    ok = add_note(auth_client, subject["id"], tags=twenty)
    assert ok["tags"] == twenty

    response = auth_client.post(
        notes_path(subject["id"]),
        json={
            "kind": "remember",
            "title": "제목",
            "tags": [f"tag{i}" for i in range(21)],
        },
    )

    error = assert_validation_error(response, "tags")
    assert error["fields"]["tags"] == TAGS_MESSAGE
    assert_counts(auth_client, subject["id"], total=1, open_=0)


def test_f3_정리로_20개_이하가_되는_입력은_201이다(auth_client):
    subject = create_subject(auth_client)
    # 25개를 보내지만 대소문자·공백 정리와 중복 제거 뒤에는 5개다.
    raw = []
    for i in range(5):
        raw += [f"Tag{i}", f"tag{i}", f"  TAG{i} ", f"tag{i}", f"TaG{i}"]
    assert len(raw) == 25

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": raw},
    )

    assert response.status_code == 201, response.text
    assert response.json()["tags"] == [f"tag{i}" for i in range(5)]


def test_f3_21개를_보내도_중복_제거_뒤_20개이면_201이다(auth_client):
    subject = create_subject(auth_client)
    raw = [f"tag{i}" for i in range(20)] + ["TAG0"]

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": raw},
    )

    assert response.status_code == 201, response.text
    assert response.json()["tags"] == [f"tag{i}" for i in range(20)]


@pytest.mark.parametrize(
    "tags",
    ["pandas", 5, True, {"a": 1}, {}, ""],
    ids=lambda v: repr(v),
)
def test_f3_tags가_배열이_아니면_422다(auth_client, tags):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": tags},
    )

    assert_validation_error(response, "tags")
    assert_counts(auth_client, subject["id"], total=0, open_=0)


@pytest.mark.parametrize(
    "tags",
    [[1], [None], [True], [["a"]], [{"a": 1}], ["ok", 2], ["ok", None]],
    ids=lambda v: repr(v),
)
def test_f3_tags_원소가_문자열이_아니면_422다(auth_client, tags):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "tags": tags},
    )

    assert_validation_error(response, "tags")
    assert_counts(auth_client, subject["id"], total=0, open_=0)


# --- is_open ---


@pytest.mark.parametrize("value", [True, False])
def test_f3_is_open_불리언을_그대로_저장한다(auth_client, value):
    subject = create_subject(auth_client)

    note = add_note(auth_client, subject["id"], is_open=value)

    assert note["is_open"] is value
    assert get_note(auth_client, note["id"])["is_open"] is value


@pytest.mark.parametrize(
    "value",
    ["true", "false", "yes", "", "0", "1", 1, 0, 2, 0.5, [], {}],
    ids=lambda v: repr(v),
)
def test_f3_is_open이_불리언이_아니면_422다(auth_client, value):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "remember", "title": "제목", "is_open": value},
    )

    assert_validation_error(response, "is_open")
    assert_counts(auth_client, subject["id"], total=0, open_=0)


# --- 여러 필드 오류 ---


def test_f3_여러_필드가_틀리면_fields에_모두_담긴다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        json={"kind": "memo", "title": "", "tags": [""], "is_open": "yes"},
    )

    error = assert_validation_error(response, "kind", "title", "tags", "is_open")
    assert set(error["fields"]) == {"kind", "title", "tags", "is_open"}
    assert_counts(auth_client, subject["id"], total=0, open_=0)


# ---------------------------------------------------------------------------
# 없는 주제·잘못된 id·415·401
# ---------------------------------------------------------------------------


def test_f3_없는_주제에_노트를_만들면_404다(auth_client):
    response = auth_client.post(notes_path(9999), json={"kind": "remember", "title": "제목"})

    assert_subject_not_found(response)


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f3_정수가_아니거나_범위_밖인_주제_id로_노트를_만들면_404다(auth_client, bad_id):
    response = auth_client.post(notes_path(bad_id), json={"kind": "remember", "title": "제목"})

    assert_subject_not_found(response)


def test_f3_없는_노트를_조회하면_404다(auth_client):
    assert_note_not_found(auth_client.get(note_path(9999)))


def test_f3_없는_노트를_수정하면_404다(auth_client):
    assert_note_not_found(auth_client.patch(note_path(9999), json={"title": "x"}))


def test_f3_없는_노트를_삭제하면_404다(auth_client):
    assert_note_not_found(auth_client.delete(note_path(9999)))


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f3_정수가_아니거나_범위_밖인_노트_id는_404다(auth_client, bad_id):
    assert_note_not_found(auth_client.get(note_path(bad_id)))
    assert_note_not_found(auth_client.patch(note_path(bad_id), json={"title": "x"}))
    assert_note_not_found(auth_client.delete(note_path(bad_id)))


def test_f3_존재하지_않는_바로_다음_id는_404다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])

    assert_note_not_found(auth_client.get(note_path(note["id"] + 1)))


def test_f3_POST가_JSON이_아니면_415다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        content="kind=remember&title=abc",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_POST의_Content_Type이_text_plain이면_415다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        notes_path(subject["id"]),
        content='{"kind": "remember", "title": "abc"}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert_counts(auth_client, subject["id"], total=0, open_=0)


def test_f3_PATCH가_JSON이_아니면_415다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(note["id"]),
        content="title=바꿈",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert get_note(auth_client, note["id"]) == note


def test_f3_로그인하지_않으면_모든_노트_API가_401이다(client):
    responses = [
        client.post(notes_path(1), json={"kind": "remember", "title": "제목"}),
        client.get(note_path(1)),
        client.patch(note_path(1), json={"title": "x"}),
        client.delete(note_path(1)),
    ]

    for response in responses:
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# 수정 (PATCH /api/notes/{id})
# ---------------------------------------------------------------------------


def make_full_note(client: TestClient, subject_id: int) -> dict:
    return add_note(
        client,
        subject_id,
        kind="debug",
        title="원래 제목",
        body="원래 본문",
        tags=["a", "b"],
        is_open=True,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "review"),
        ("title", "새 제목"),
        ("body", "새 본문\n\n```python\nprint(1)\n```"),
        ("tags", ["x", "y", "z"]),
        ("is_open", False),
    ],
    ids=["kind", "title", "body", "tags", "is_open"],
)
def test_f3_PATCH는_보낸_필드만_수정한다(auth_client, field, value):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={field: value})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == NOTE_KEYS
    assert body[field] == value
    for key in ("id", "subject_id", "kind", "title", "body", "tags", "is_open", "created_at"):
        if key != field:
            assert body[key] == original[key], key
    assert get_note(auth_client, original["id"]) == body


def test_f3_PATCH는_여러_필드를_한꺼번에_수정한다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(original["id"]),
        json={"kind": "review", "title": "후기로 변경", "body": "", "tags": [], "is_open": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "review"
    assert body["title"] == "후기로 변경"
    assert body["body"] == ""
    assert body["tags"] == []
    assert body["is_open"] is False
    assert get_note(auth_client, original["id"]) == body


def test_f3_설계_예시_PATCH_미해결_질문에_답을_채운다(auth_client):
    subject = create_subject(auth_client)
    question = add_note(
        auth_client,
        subject["id"],
        kind="remember",
        title="isna와 isnull 차이?",
        body="",
        tags=["pandas"],
        is_open=True,
    )
    assert_counts(auth_client, subject["id"], total=1, open_=1)

    response = auth_client.patch(
        note_path(question["id"]),
        json={
            "body": "isna()는 isnull()의 별칭이다. 동작이 같고 R 사용자를 위해 둘 다 둔 것",
            "is_open": False,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["body"] == "isna()는 isnull()의 별칭이다. 동작이 같고 R 사용자를 위해 둘 다 둔 것"
    assert body["is_open"] is False
    assert body["title"] == "isna와 isnull 차이?"
    assert body["tags"] == ["pandas"]
    assert body["kind"] == "remember"
    assert get_note(auth_client, question["id"]) == body
    assert_counts(auth_client, subject["id"], total=1, open_=0)


def test_f3_PATCH의_빈_객체는_200이고_아무것도_바꾸지_않는다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={})

    assert response.status_code == 200, response.text
    assert response.json() == original
    assert get_note(auth_client, original["id"]) == original


def test_f3_PATCH도_태그를_정리해서_저장한다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(original["id"]), json={"tags": [" Pandas ", "CSV", "pandas"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["tags"] == ["pandas", "csv"]
    assert get_note(auth_client, original["id"])["tags"] == ["pandas", "csv"]


def test_f3_PATCH도_정리로_20개_이하가_되면_200이다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])
    raw = [f"Tag{i}" for i in range(5)] * 5
    assert len(raw) == 25

    response = auth_client.patch(note_path(original["id"]), json={"tags": raw})

    assert response.status_code == 200, response.text
    assert response.json()["tags"] == [f"tag{i}" for i in range(5)]


def test_f3_PATCH로_본문을_빈_문자열로_지울_수_있다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={"body": ""})

    assert response.status_code == 200, response.text
    assert response.json()["body"] == ""


def test_f3_PATCH로_마크다운_원문이_그대로_저장된다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])
    body = "<script>alert(1)</script>\n\n" + MARKDOWN_BODY

    response = auth_client.patch(note_path(original["id"]), json={"body": body})

    assert response.status_code == 200, response.text
    assert response.json()["body"] == body
    assert get_note(auth_client, original["id"])["body"] == body


def test_f3_PATCH_본문에_id_subject_id_created_at을_넣어도_무시한다(auth_client):
    subject = create_subject(auth_client)
    other = create_subject(auth_client, "다른 주제")
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(original["id"]),
        json={
            "id": 99999,
            "subject_id": other["id"],
            "created_at": "2000-01-01T00:00:00Z",
            "title": "제목만 바뀜",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == original["id"]
    assert body["subject_id"] == subject["id"]
    assert body["created_at"] == original["created_at"]
    assert body["title"] == "제목만 바뀜"
    assert_note_not_found(auth_client.get(note_path(99999)))
    assert get_note(auth_client, original["id"])["subject_id"] == subject["id"]
    assert_counts(auth_client, subject["id"], total=1, open_=1)
    assert_counts(auth_client, other["id"], total=0, open_=0)


def test_f3_PATCH가_updated_at만_갱신하고_created_at은_그대로_둔다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])
    assert original["updated_at"] == original["created_at"]

    # 응답 시각이 초 단위라 실제로 값이 바뀌는지 보려면 1초 넘게 기다려야 한다.
    time.sleep(1.1)

    empty = auth_client.patch(note_path(original["id"]), json={})
    assert empty.status_code == 200
    assert empty.json()["updated_at"] == original["updated_at"]

    response = auth_client.patch(note_path(original["id"]), json={"title": "시각 확인"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert DATETIME_RE.match(body["updated_at"])
    assert body["created_at"] == original["created_at"]
    assert body["updated_at"] > original["updated_at"]
    assert body["updated_at"] > body["created_at"]
    assert get_note(auth_client, original["id"])["updated_at"] == body["updated_at"]


def test_f3_PATCH는_다른_노트에_영향을_주지_않는다(auth_client):
    subject = create_subject(auth_client)
    first = make_full_note(auth_client, subject["id"])
    second = add_note(auth_client, subject["id"], title="둘째")

    auth_client.patch(note_path(first["id"]), json={"title": "첫째 수정", "is_open": False})

    assert get_note(auth_client, second["id"]) == second


# --- PATCH 검증 오류 ---


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "memo"),
        ("kind", ""),
        ("kind", "DEBUG"),
        ("kind", 1),
        ("title", ""),
        ("title", "   "),
        ("title", "가" * 201),
        ("title", 123),
        ("body", "가" * 50001),
        ("body", 123),
        ("tags", ["가" * 31]),
        ("tags", [f"t{i}" for i in range(21)]),
        ("tags", [""]),
        ("tags", ["  "]),
        ("tags", "pandas"),
        ("tags", [1]),
        ("is_open", "yes"),
        ("is_open", "true"),
        ("is_open", 1),
        ("is_open", 0),
    ],
    ids=lambda v: repr(v)[:30],
)
def test_f3_PATCH가_검증에_실패하면_422이고_값은_그대로다(auth_client, field, value):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={field: value})

    assert_validation_error(response, field)
    assert get_note(auth_client, original["id"]) == original
    assert_counts(auth_client, subject["id"], total=1, open_=1)


@pytest.mark.parametrize("field", ["kind", "title", "body", "tags", "is_open"])
def test_f3_PATCH에서_null을_보내면_422이고_값은_그대로다(auth_client, field):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={field: None})

    assert_validation_error(response, field)
    assert get_note(auth_client, original["id"]) == original


def test_f3_PATCH의_일부만_틀려도_유효한_필드까지_저장하지_않는다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(original["id"]),
        json={"title": "바뀌면 안 됨", "body": "바뀌면 안 됨", "kind": "memo"},
    )

    error = assert_validation_error(response, "kind")
    assert "title" not in error["fields"]
    assert get_note(auth_client, original["id"]) == original


def test_f3_PATCH_422는_긴_본문을_fields_body로_알린다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={"body": "a" * 50001})

    error = assert_validation_error(response, "body")
    assert set(error["fields"]) == {"body"}


def test_f3_PATCH_제목_200자는_저장된다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(note_path(original["id"]), json={"title": "가" * 200})

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "가" * 200


# ---------------------------------------------------------------------------
# 삭제 (완료 기준 4)
# ---------------------------------------------------------------------------


def test_f3_삭제하면_204이고_본문이_없다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])

    response = auth_client.delete(note_path(note["id"]))

    assert response.status_code == 204
    assert response.content == b""


def test_f3_삭제한_노트는_GET이_404다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])
    assert get_note(auth_client, note["id"]) == note

    assert auth_client.delete(note_path(note["id"])).status_code == 204

    assert_note_not_found(auth_client.get(note_path(note["id"])))


def test_f3_삭제한_노트를_다시_삭제하거나_수정하면_404다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])
    assert auth_client.delete(note_path(note["id"])).status_code == 204

    assert_note_not_found(auth_client.delete(note_path(note["id"])))
    assert_note_not_found(auth_client.patch(note_path(note["id"]), json={"title": "x"}))


def test_f3_삭제하면_주제의_note_count가_줄어든다(auth_client):
    subject = create_subject(auth_client)
    keep = add_note(auth_client, subject["id"], title="남김")
    gone = add_note(auth_client, subject["id"], title="삭제")
    assert_counts(auth_client, subject["id"], total=2, open_=0)

    assert auth_client.delete(note_path(gone["id"])).status_code == 204

    assert_counts(auth_client, subject["id"], total=1, open_=0)
    assert get_note(auth_client, keep["id"]) == keep


def test_f3_미해결_노트를_삭제하면_open_note_count도_줄어든다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="해결됨", is_open=False)
    open_note = add_note(auth_client, subject["id"], title="미해결", is_open=True)
    assert_counts(auth_client, subject["id"], total=2, open_=1)

    assert auth_client.delete(note_path(open_note["id"])).status_code == 204

    assert_counts(auth_client, subject["id"], total=1, open_=0)


def test_f3_다른_주제의_노트를_삭제해도_이_주제의_개수는_그대로다(auth_client):
    a = create_subject(auth_client, "A")
    b = create_subject(auth_client, "B")
    add_note(auth_client, a["id"], is_open=True)
    b_note = add_note(auth_client, b["id"], is_open=True)

    assert auth_client.delete(note_path(b_note["id"])).status_code == 204

    assert_counts(auth_client, a["id"], total=1, open_=1)
    assert_counts(auth_client, b["id"], total=0, open_=0)


# ---------------------------------------------------------------------------
# 주제의 note_count, open_note_count
# ---------------------------------------------------------------------------


def test_f3_노트가_없는_주제는_개수가_0이다(auth_client):
    subject = create_subject(auth_client)

    assert_counts(auth_client, subject["id"], total=0, open_=0)
    assert isinstance(note_counts(auth_client, subject["id"])["note_count"], int)


def test_f3_생성하면_note_count와_open_note_count가_늘어난다(auth_client):
    subject = create_subject(auth_client)

    add_note(auth_client, subject["id"], is_open=False)
    assert_counts(auth_client, subject["id"], total=1, open_=0)

    add_note(auth_client, subject["id"], is_open=True)
    assert_counts(auth_client, subject["id"], total=2, open_=1)

    add_note(auth_client, subject["id"], is_open=True)
    add_note(auth_client, subject["id"])
    assert_counts(auth_client, subject["id"], total=4, open_=2)


def test_f3_is_open을_바꾸면_open_note_count만_바뀐다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"], is_open=False)
    add_note(auth_client, subject["id"], is_open=False)
    assert_counts(auth_client, subject["id"], total=2, open_=0)

    patched = auth_client.patch(note_path(note["id"]), json={"is_open": True})
    assert patched.status_code == 200
    assert_counts(auth_client, subject["id"], total=2, open_=1)

    patched = auth_client.patch(note_path(note["id"]), json={"is_open": False})
    assert patched.status_code == 200
    assert_counts(auth_client, subject["id"], total=2, open_=0)


def test_f3_is_open이_아닌_필드를_수정해도_개수는_그대로다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"], is_open=True)

    auth_client.patch(note_path(note["id"]), json={"title": "수정", "kind": "debug"})

    assert_counts(auth_client, subject["id"], total=1, open_=1)


def test_f3_개수는_주제끼리_섞이지_않는다(auth_client):
    a = create_subject(auth_client, "A")
    b = create_subject(auth_client, "B")
    c = create_subject(auth_client, "C")

    add_note(auth_client, a["id"], is_open=True)
    add_note(auth_client, a["id"], is_open=False)
    add_note(auth_client, a["id"], is_open=True)
    add_note(auth_client, b["id"], is_open=False)

    assert_counts(auth_client, a["id"], total=3, open_=2)
    assert_counts(auth_client, b["id"], total=1, open_=0)
    assert_counts(auth_client, c["id"], total=0, open_=0)


def test_f3_생성에_실패하면_개수가_늘지_않는다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], is_open=True)

    bad = auth_client.post(
        notes_path(subject["id"]), json={"kind": "remember", "title": "", "is_open": True}
    )

    assert bad.status_code == 422
    assert_counts(auth_client, subject["id"], total=1, open_=1)


# ---------------------------------------------------------------------------
# 화면 (S4, S5)
# ---------------------------------------------------------------------------


def test_f3_로그인하면_노트_작성_화면이_200이다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(f"/subjects/{subject['id']}/notes/new", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f3_로그인하면_노트_보기_화면이_200이다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"], body=MARKDOWN_BODY)

    response = auth_client.get(f"/notes/{note['id']}", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f3_로그인하면_노트_수정_화면이_200이다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"])

    response = auth_client.get(f"/notes/{note['id']}/edit", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f3_로그인하지_않으면_노트_화면은_login으로_이동한다(client):
    for path in ("/subjects/1/notes/new", "/notes/1", "/notes/1/edit"):
        response = client.get(path, follow_redirects=False)

        assert response.status_code == 302, path
        assert response.headers["location"] == "/login"


# ---------------------------------------------------------------------------
# 리뷰 라운드 1: 짝 없는 서로게이트 이스케이프(\ud800)
# ---------------------------------------------------------------------------

RAW_JSON_HEADERS = {"Content-Type": "application/json"}


def test_f3_짝_없는_서로게이트_태그로_노트를_만들면_422이고_저장되지_않는다(auth_client):
    subject = create_subject(auth_client)
    before = note_counts(auth_client, subject["id"])

    response = auth_client.post(
        notes_path(subject["id"]),
        content='{"kind":"remember","title":"t","tags":["\\ud800"]}',
        headers=RAW_JSON_HEADERS,
    )

    error = assert_validation_error(response, "tags")
    assert error["fields"]["tags"] == TAGS_MESSAGE
    assert note_counts(auth_client, subject["id"]) == before


def test_f3_짝_없는_서로게이트_태그로_PATCH하면_422이고_태그가_그대로다(auth_client):
    subject = create_subject(auth_client)
    original = make_full_note(auth_client, subject["id"])

    response = auth_client.patch(
        note_path(original["id"]),
        content='{"tags":["\\ud800"]}',
        headers=RAW_JSON_HEADERS,
    )

    error = assert_validation_error(response, "tags")
    assert error["fields"]["tags"] == TAGS_MESSAGE
    after = auth_client.get(note_path(original["id"]))
    assert after.status_code == 200, after.text
    assert after.json()["tags"] == original["tags"]
    assert after.json() == original


# ===========================================================================
# F4 노트 검색·필터 (GET /api/subjects/{id}/notes)
#
# 완료 기준
# 1. 필터 조건을 하나 이상 걸면 조건을 모두(AND) 만족하는 노트만 수정 최신순으로
#    20개씩 나오고, 21개 이상이면 다음 페이지(더 보기)로 다음 20개가 이어진다.
# 2. 검색어는 제목과 본문에 대소문자 구분 없이 부분 일치한다.
# 3. 결과가 없으면 빈 목록이다(문구는 화면 몫이라 자동 테스트 대상이 아니다).
#
# 해석
# - 응답의 tags는 문자 코드 순으로 정렬한다(영문 다음 한글).
# - q는 앞뒤 공백을 지우고, 비어 있으면 조건이 없다. 대소문자 무시는 ASCII 글자에 적용된다.
#   %와 _는 글자 그대로 찾는다.
# - open=true만 조건이다. open=false나 생략은 조건 없음이고, 불리언이 아닌 값은 422다.
# - tag는 저장된 값과 정확히 일치해야 한다(쿼리 값을 소문자로 바꾸지 않는다).
#   여러 개면 모두 포함해야 한다.
# - 같은 updated_at이면 id 내림차순이다.
# - page는 1 이상, limit은 1~100 정수다. 벗어나면 422다.
# ===========================================================================

LIST_KEYS = {"items", "total", "page", "limit", "tags"}


def list_notes(client: TestClient, subject_id, params=None) -> dict:
    """GET 목록을 호출해 200을 확인하고 본문을 돌려준다. params는 dict 또는 (키, 값) 목록."""
    response = client.get(notes_path(subject_id), params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == LIST_KEYS
    return body


def ids_of(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


def titles_of(body: dict) -> list[str]:
    return [item["title"] for item in body["items"]]


def make_many(client: TestClient, subject_id: int, count: int, **fields) -> list[dict]:
    """제목이 '노트 NN'인 노트를 만든 순서대로 count개 만든다."""
    return [
        add_note(client, subject_id, title=f"노트 {index:02d}", **fields) for index in range(count)
    ]


# --- 기본 모양 --------------------------------------------------------------


def test_f4_노트가_없는_주제는_빈_목록과_기본_page_limit을_돌려준다(auth_client):
    subject = create_subject(auth_client)

    body = list_notes(auth_client, subject["id"])

    assert body == {"items": [], "total": 0, "page": 1, "limit": 20, "tags": []}


def test_f4_응답에_items_total_page_limit_tags가_있고_원소는_Note_전체다(auth_client):
    subject = create_subject(auth_client)
    created = add_note(
        auth_client,
        subject["id"],
        kind="debug",
        title="인코딩 오류",
        body=MARKDOWN_BODY,
        tags=["pandas", "csv"],
        is_open=True,
    )

    body = list_notes(auth_client, subject["id"])

    assert body["items"] == [created]
    assert set(body["items"][0]) == NOTE_KEYS
    assert body["items"][0]["body"] == MARKDOWN_BODY
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["limit"] == 20


def test_f4_조건_없이_부르면_주제의_모든_노트가_나온다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 3)
    add_note(auth_client, subject["id"], kind="debug", title="디버깅", is_open=True)
    add_note(auth_client, subject["id"], kind="review", title="후기")

    body = list_notes(auth_client, subject["id"])

    assert body["total"] == 5
    assert len(body["items"]) == 5


def test_f4_설계_예시_요청_kind_remember_open_true_q_isna를_그대로_재현한다(auth_client):
    subject = create_subject(auth_client)
    add_note(
        auth_client,
        subject["id"],
        kind="remember",
        title="csv 저장 시 인덱스 제외",
        tags=["pandas", "csv"],
    )
    target = add_note(
        auth_client,
        subject["id"],
        kind="remember",
        title="DataFrame의 isnull()과 isna()가 다른 이유?",
        body="",
        tags=["pandas"],
        is_open=True,
    )
    add_note(auth_client, subject["id"], kind="debug", title="isna 오류", is_open=True)
    add_note(auth_client, subject["id"], kind="remember", title="isna 정리", is_open=False)
    add_note(
        auth_client,
        subject["id"],
        kind="remember",
        title="날짜 변환",
        tags=["datetime"],
        is_open=True,
    )

    response = auth_client.get(
        f"/api/subjects/{subject['id']}/notes?kind=remember&open=true&q=isna"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [target],
        "total": 1,
        "page": 1,
        "limit": 20,
        "tags": ["csv", "datetime", "pandas"],
    }
    assert target["body"] == ""
    assert target["tags"] == ["pandas"]
    assert target["is_open"] is True


# --- AND 조합 ---------------------------------------------------------------

AND_SPECS = [
    # (kind, title, body, tags, is_open)
    ("remember", "isna 차이", "", ["pandas", "csv"], True),
    ("remember", "ISNA 정리", "별칭", ["pandas"], False),
    ("debug", "인코딩 오류", "isna 호출 중 발생", ["pandas", "csv"], True),
    ("review", "회고", "csv 파일 정리", ["csv"], True),
    ("remember", "csv 저장", "인덱스 제외", ["pandas", "csv"], True),
    ("debug", "날짜 파싱", "", ["datetime"], False),
    ("review", "후기", "ISNA 와 비교", [], False),
    ("remember", "아무 조건 없음", "", [], False),
]

AND_CONDITIONS = {
    "kind": "remember",
    "tag": "csv",
    "q": "isna",
    "open": "true",
}


def and_oracle(specs, kind=None, tags=(), q=None, open_only=False) -> set[str]:
    """조건을 모두 만족하는 노트의 제목 집합(테스트용 독립 계산)."""
    found = set()
    for spec_kind, title, body, spec_tags, is_open in specs:
        if kind is not None and spec_kind != kind:
            continue
        if any(tag not in spec_tags for tag in tags):
            continue
        if q is not None and q.lower() not in (title + "\n" + body).lower():
            continue
        if open_only and not is_open:
            continue
        found.add(title)
    return found


def make_and_dataset(client: TestClient) -> dict:
    subject = create_subject(client)
    for kind, title, body, tags, is_open in AND_SPECS:
        add_note(
            client, subject["id"], kind=kind, title=title, body=body, tags=tags, is_open=is_open
        )
    return subject


def _and_combinations():
    names = list(AND_CONDITIONS)
    combos = []
    for size in (2, 3, 4):
        for chosen in itertools.combinations(names, size):
            combos.append(chosen)
    return combos


@pytest.mark.parametrize("chosen", _and_combinations(), ids="+".join)
def test_f4_조건을_둘_셋_넷_걸면_모두_만족하는_노트만_나온다(auth_client, chosen):
    subject = make_and_dataset(auth_client)
    params = [(name, AND_CONDITIONS[name]) for name in chosen]

    body = list_notes(auth_client, subject["id"], params)

    expected = and_oracle(
        AND_SPECS,
        kind=AND_CONDITIONS["kind"] if "kind" in chosen else None,
        tags=(AND_CONDITIONS["tag"],) if "tag" in chosen else (),
        q=AND_CONDITIONS["q"] if "q" in chosen else None,
        open_only="open" in chosen,
    )
    assert expected, "테스트 자료가 잘못되었다: 기대 결과가 비어 있다"
    assert set(titles_of(body)) == expected
    assert len(body["items"]) == len(expected)
    assert body["total"] == len(expected)


def test_f4_네_조건을_모두_걸면_한_노트만_남는다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], AND_CONDITIONS)

    assert titles_of(body) == ["isna 차이"]
    assert body["total"] == 1


def test_f4_조건_하나라도_어긋나면_결과가_비어_있다(auth_client):
    subject = make_and_dataset(auth_client)

    # remember 이면서 csv 태그이고 미해결이며 isna를 포함하는 노트는 있지만
    # 태그를 datetime으로 바꾸면 조건을 모두 만족하는 노트가 없다.
    body = list_notes(
        auth_client,
        subject["id"],
        {"kind": "remember", "tag": "datetime", "q": "isna", "open": "true"},
    )

    assert body["items"] == []
    assert body["total"] == 0


def test_f4_kind만_걸어도_그_유형만_나온다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"kind": "review"})

    assert set(titles_of(body)) == {"회고", "후기"}
    assert {item["kind"] for item in body["items"]} == {"review"}


@pytest.mark.parametrize("kind", ["remember", "debug", "review"])
def test_f4_kind_세_값은_각각_그_유형만_거른다(auth_client, kind):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"kind": kind})

    assert set(titles_of(body)) == and_oracle(AND_SPECS, kind=kind)
    assert {item["kind"] for item in body["items"]} == {kind}
    assert body["total"] == len(body["items"])


@pytest.mark.parametrize("kind", ["other", "REMEMBER", "all", "Debug"])
def test_f4_kind가_세_값이_아니면_422다(auth_client, kind):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"kind": kind})

    error = assert_validation_error(response, "kind")
    assert error["fields"]["kind"] == KIND_MESSAGE


def test_f4_kind가_잘못되면_다른_조건이_맞아도_422다(auth_client):
    subject = make_and_dataset(auth_client)

    response = auth_client.get(
        notes_path(subject["id"]),
        params={"kind": "bogus", "tag": "csv", "q": "isna", "open": "true"},
    )

    error = assert_validation_error(response, "kind")
    assert error["fields"]["kind"] == KIND_MESSAGE


# --- open -------------------------------------------------------------------


def test_f4_open_true면_미해결_노트만_나온다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"open": "true"})

    assert set(titles_of(body)) == and_oracle(AND_SPECS, open_only=True)
    assert all(item["is_open"] is True for item in body["items"])
    assert body["total"] == len(body["items"])


def test_f4_open_false와_open_생략은_조건_없음이다(auth_client):
    subject = make_and_dataset(auth_client)

    omitted = list_notes(auth_client, subject["id"])
    explicit_false = list_notes(auth_client, subject["id"], {"open": "false"})

    assert omitted["total"] == len(AND_SPECS)
    assert explicit_false["total"] == len(AND_SPECS)
    assert ids_of(explicit_false) == ids_of(omitted)
    assert {item["is_open"] for item in explicit_false["items"]} == {True, False}


@pytest.mark.parametrize("value", ["abc", "maybe", "2", "yesno"])
def test_f4_open이_불리언이_아니면_422다(auth_client, value):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"open": value})

    assert_validation_error(response, "open")


def test_f4_미해결로_바꾼_노트는_open_true_목록에_들어온다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"], title="질문", is_open=True)
    assert list_notes(auth_client, subject["id"], {"open": "true"})["total"] == 1

    response = auth_client.patch(note_path(note["id"]), json={"is_open": False})
    assert response.status_code == 200, response.text

    body = list_notes(auth_client, subject["id"], {"open": "true"})
    assert body["items"] == []
    assert body["total"] == 0
    assert list_notes(auth_client, subject["id"])["total"] == 1


# --- 태그 필터 ---------------------------------------------------------------


def test_f4_tag_하나로_그_태그를_가진_노트만_나온다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"tag": "csv"})

    assert set(titles_of(body)) == and_oracle(AND_SPECS, tags=("csv",))
    assert all("csv" in item["tags"] for item in body["items"])


def test_f4_tag를_둘_주면_둘_다_가진_노트만_나온다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], [("tag", "pandas"), ("tag", "csv")])

    assert set(titles_of(body)) == and_oracle(AND_SPECS, tags=("pandas", "csv"))
    assert set(titles_of(body)) == {"isna 차이", "인코딩 오류", "csv 저장"}
    for item in body["items"]:
        assert {"pandas", "csv"} <= set(item["tags"])
    # 하나만 가진 노트(pandas만, csv만)는 빠진다.
    assert "ISNA 정리" not in titles_of(body)
    assert "회고" not in titles_of(body)


def test_f4_tag를_순서를_바꿔_줘도_결과가_같다(auth_client):
    subject = make_and_dataset(auth_client)

    first = list_notes(auth_client, subject["id"], [("tag", "pandas"), ("tag", "csv")])
    second = list_notes(auth_client, subject["id"], [("tag", "csv"), ("tag", "pandas")])

    assert first == second


def test_f4_서로_겹치지_않는_tag_둘이면_빈_결과다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], [("tag", "csv"), ("tag", "datetime")])

    assert body["items"] == []
    assert body["total"] == 0


def test_f4_tag는_부분_일치가_아니라_정확히_일치한다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="판다스", tags=["pandas"])
    add_note(auth_client, subject["id"], title="csv 하나", tags=["csv"])
    add_note(auth_client, subject["id"], title="csv 둘", tags=["csv2"])
    add_note(auth_client, subject["id"], title="접두", tags=["my-csv"])

    prefix = list_notes(auth_client, subject["id"], {"tag": "pan"})
    exact = list_notes(auth_client, subject["id"], {"tag": "csv"})
    suffix = list_notes(auth_client, subject["id"], {"tag": "das"})

    assert prefix["items"] == []
    assert prefix["total"] == 0
    assert titles_of(exact) == ["csv 하나"]
    assert suffix["items"] == []


def test_f4_대문자_tag_쿼리는_일치하지_않는다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="판다스", tags=["pandas"])

    upper = list_notes(auth_client, subject["id"], {"tag": "PANDAS"})
    mixed = list_notes(auth_client, subject["id"], {"tag": "Pandas"})
    lower = list_notes(auth_client, subject["id"], {"tag": "pandas"})

    assert upper["items"] == []
    assert mixed["items"] == []
    assert titles_of(lower) == ["판다스"]


def test_f4_대문자로_저장한_태그는_소문자로_정리되어_소문자_쿼리로_찾는다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="대문자 태그", tags=["  Pandas "])

    body = list_notes(auth_client, subject["id"], {"tag": "pandas"})

    assert titles_of(body) == ["대문자 태그"]
    assert body["items"][0]["tags"] == ["pandas"]


def test_f4_없는_태그는_빈_결과다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"tag": "no-such-tag"})

    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["limit"] == 20


def test_f4_한글_태그도_정확히_일치로_거른다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="한글 태그", tags=["데이터"])
    add_note(auth_client, subject["id"], title="긴 한글 태그", tags=["데이터분석"])

    body = list_notes(auth_client, subject["id"], {"tag": "데이터"})

    assert titles_of(body) == ["한글 태그"]


# --- 응답 tags ----------------------------------------------------------------


def test_f4_tags는_필터와_무관하게_주제_노트의_모든_태그다(auth_client):
    subject = make_and_dataset(auth_client)
    everything = list_notes(auth_client, subject["id"])["tags"]

    assert everything == ["csv", "datetime", "pandas"]
    for params in (
        {"kind": "debug"},
        {"tag": "datetime"},
        {"q": "isna", "open": "true"},
        {"tag": "no-such-tag"},
        {"kind": "review", "tag": "csv", "q": "회고", "open": "true"},
        [("tag", "pandas"), ("tag", "csv")],
        {"page": "9"},
    ):
        assert list_notes(auth_client, subject["id"], params)["tags"] == everything


def test_f4_tags는_중복이_없고_문자_코드_순이다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="a", tags=["pandas", "csv", "한글"])
    add_note(auth_client, subject["id"], title="b", tags=["csv", "datetime", "가나다"])
    add_note(auth_client, subject["id"], title="c", tags=["pandas", "a1", "Zeta"])
    add_note(auth_client, subject["id"], title="d", tags=[])

    body = list_notes(auth_client, subject["id"])

    assert len(body["tags"]) == len(set(body["tags"]))
    assert body["tags"] == sorted({"pandas", "csv", "한글", "datetime", "가나다", "a1", "zeta"})
    assert body["tags"] == ["a1", "csv", "datetime", "pandas", "zeta", "가나다", "한글"]


def test_f4_tags에_다른_주제의_태그가_섞이지_않는다(auth_client):
    first = create_subject(auth_client, "주제 하나")
    second = create_subject(auth_client, "주제 둘")
    add_note(auth_client, first["id"], title="하나", tags=["pandas", "csv"])
    add_note(auth_client, second["id"], title="둘", tags=["sql", "csv", "join"])

    assert list_notes(auth_client, first["id"])["tags"] == ["csv", "pandas"]
    assert list_notes(auth_client, second["id"])["tags"] == ["csv", "join", "sql"]


def test_f4_노트에_태그가_하나도_없으면_tags는_빈_배열이다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 2)

    body = list_notes(auth_client, subject["id"])

    assert body["total"] == 2
    assert body["tags"] == []


# --- 검색어 q -----------------------------------------------------------------

SEARCH_SPECS = [
    # (title, body)
    ("DataFrame 기초", ""),
    ("제목에는 없음", "본문에만 Needle 이 있다"),
    ("한글 검색어 테스트", "파이썬 판다스"),
    ("100% 완료", ""),
    ("100 완료", "퍼센트 없음"),
    ("a_b 변수", ""),
    ("axb 변수", ""),
    ("it's a trap", ""),
    ("경로 C:\\temp", ""),
    ("경로 C:/temp", ""),
    ("공백 포함", "x"),
]


def make_search_dataset(client: TestClient) -> dict:
    subject = create_subject(client)
    for title, body in SEARCH_SPECS:
        add_note(client, subject["id"], title=title, body=body)
    return subject


def search(client: TestClient, subject_id: int, q: str) -> dict:
    return list_notes(client, subject_id, {"q": q})


def test_f4_검색어는_제목에_부분_일치한다(auth_client):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], "Frame")

    assert titles_of(body) == ["DataFrame 기초"]
    assert body["total"] == 1


def test_f4_검색어는_본문에_부분_일치한다(auth_client):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], "Needle")

    assert titles_of(body) == ["제목에는 없음"]
    assert body["items"][0]["body"] == "본문에만 Needle 이 있다"


@pytest.mark.parametrize("q", ["dataframe", "DATAFRAME", "dAtAfRaMe", "DataFrame"])
def test_f4_검색어는_제목에서_대소문자를_구분하지_않는다(auth_client, q):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], q)

    assert titles_of(body) == ["DataFrame 기초"]


@pytest.mark.parametrize("q", ["needle", "NEEDLE", "nEeDlE"])
def test_f4_검색어는_본문에서_대소문자를_구분하지_않는다(auth_client, q):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], q)

    assert titles_of(body) == ["제목에는 없음"]


def test_f4_소문자로_저장한_본문을_대문자_검색어로도_찾는다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="소문자", body="isna is an alias of isnull")

    assert titles_of(search(auth_client, subject["id"], "ISNULL")) == ["소문자"]
    assert titles_of(search(auth_client, subject["id"], "Alias")) == ["소문자"]


def test_f4_한글_검색어도_부분_일치한다(auth_client):
    subject = make_search_dataset(auth_client)

    by_title = search(auth_client, subject["id"], "검색어")
    by_body = search(auth_client, subject["id"], "판다스")

    assert titles_of(by_title) == ["한글 검색어 테스트"]
    assert titles_of(by_body) == ["한글 검색어 테스트"]


def test_f4_제목과_본문_둘_다_일치해도_노트는_한_번만_나온다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="isna 정리", body="isna 는 isnull 의 별칭")

    body = search(auth_client, subject["id"], "isna")

    assert len(body["items"]) == 1
    assert body["total"] == 1


def test_f4_검색어_앞뒤_공백은_지우고_찾는다(auth_client):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], "   needle \t")

    assert titles_of(body) == ["제목에는 없음"]


def test_f4_빈_검색어와_공백만_있는_검색어는_조건_없음이다(auth_client):
    subject = make_search_dataset(auth_client)

    everything = list_notes(auth_client, subject["id"])
    empty = search(auth_client, subject["id"], "")
    blank = search(auth_client, subject["id"], "   ")

    assert everything["total"] == len(SEARCH_SPECS)
    assert empty["total"] == len(SEARCH_SPECS)
    assert blank["total"] == len(SEARCH_SPECS)
    assert ids_of(empty) == ids_of(everything)
    assert ids_of(blank) == ids_of(everything)


def test_f4_빈_검색어는_다른_조건만_적용한다(auth_client):
    subject = make_and_dataset(auth_client)

    body = list_notes(auth_client, subject["id"], {"q": "  ", "kind": "debug"})

    assert set(titles_of(body)) == and_oracle(AND_SPECS, kind="debug")


def test_f4_일치하는_노트가_없으면_빈_목록이다(auth_client):
    subject = make_search_dataset(auth_client)

    body = search(auth_client, subject["id"], "zzzz-없는-검색어")

    assert body["items"] == []
    assert body["total"] == 0


def test_f4_퍼센트는_와일드카드가_아니라_글자_그대로_찾는다(auth_client):
    subject = make_search_dataset(auth_client)

    percent = search(auth_client, subject["id"], "%")
    exact = search(auth_client, subject["id"], "100%")

    assert titles_of(percent) == ["100% 완료"]
    assert titles_of(exact) == ["100% 완료"]


def test_f4_퍼센트만_있는_노트가_없으면_빈_결과다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="일반 제목", body="일반 본문")

    body = search(auth_client, subject["id"], "%")

    assert body["items"] == []
    assert body["total"] == 0


def test_f4_밑줄은_한_글자_와일드카드가_아니라_글자_그대로_찾는다(auth_client):
    subject = make_search_dataset(auth_client)

    underscore = search(auth_client, subject["id"], "_")
    pair = search(auth_client, subject["id"], "a_b")

    assert titles_of(underscore) == ["a_b 변수"]
    assert titles_of(pair) == ["a_b 변수"]
    assert "axb 변수" not in titles_of(pair)


def test_f4_밑줄과_퍼센트가_섞인_검색어도_글자_그대로다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="정확히 a_b%c")
    add_note(auth_client, subject["id"], title="정확히 aXbYYc")

    body = search(auth_client, subject["id"], "a_b%c")

    assert titles_of(body) == ["정확히 a_b%c"]


def test_f4_작은따옴표가_있는_검색어도_안전하게_찾는다(auth_client):
    subject = make_search_dataset(auth_client)

    quote = search(auth_client, subject["id"], "'")
    word = search(auth_client, subject["id"], "it's")

    assert titles_of(quote) == ["it's a trap"]
    assert titles_of(word) == ["it's a trap"]


def test_f4_SQL처럼_보이는_검색어는_조건이_아니라_글자로_취급한다(auth_client):
    subject = make_search_dataset(auth_client)

    injected = search(auth_client, subject["id"], "' OR '1'='1")
    dropped = search(auth_client, subject["id"], "'; DROP TABLE notes; --")

    assert injected["items"] == []
    assert injected["total"] == 0
    assert dropped["items"] == []
    assert list_notes(auth_client, subject["id"])["total"] == len(SEARCH_SPECS)


def test_f4_역슬래시가_있는_검색어는_글자_그대로_찾는다(auth_client):
    subject = make_search_dataset(auth_client)

    only_backslash = search(auth_client, subject["id"], "\\")
    path = search(auth_client, subject["id"], "C:\\temp")

    assert titles_of(only_backslash) == ["경로 C:\\temp"]
    assert titles_of(path) == ["경로 C:\\temp"]


def test_f4_검색어_안의_공백은_그대로_일치에_쓰인다(auth_client):
    subject = make_search_dataset(auth_client)

    hit = search(auth_client, subject["id"], "공백 포함")
    miss = search(auth_client, subject["id"], "공백  포함")

    assert titles_of(hit) == ["공백 포함"]
    assert miss["items"] == []


# --- 정렬 ---------------------------------------------------------------------


def test_f4_같은_시각에_만든_노트는_나중에_만든_것이_위에_온다(auth_client):
    subject = create_subject(auth_client)
    created = make_many(auth_client, subject["id"], 5)

    body = list_notes(auth_client, subject["id"])

    assert ids_of(body) == [note["id"] for note in reversed(created)]


def test_f4_수정한_노트가_맨_위로_오고_updated_at_내림차순으로_정렬된다(auth_client):
    subject = create_subject(auth_client)
    oldest, middle, newest = make_many(auth_client, subject["id"], 3)
    assert ids_of(list_notes(auth_client, subject["id"])) == [
        newest["id"],
        middle["id"],
        oldest["id"],
    ]

    time.sleep(1.1)
    response = auth_client.patch(note_path(oldest["id"]), json={"title": "다시 손봄"})
    assert response.status_code == 200, response.text
    edited = response.json()

    body = list_notes(auth_client, subject["id"])

    assert ids_of(body) == [oldest["id"], newest["id"], middle["id"]]
    assert body["items"][0] == edited
    assert body["items"][0]["title"] == "다시 손봄"
    updated = [item["updated_at"] for item in body["items"]]
    assert updated == sorted(updated, reverse=True)
    assert body["items"][0]["updated_at"] > body["items"][1]["updated_at"]


def test_f4_필터를_걸어도_수정_최신순이_유지된다(auth_client):
    subject = create_subject(auth_client)
    first = add_note(auth_client, subject["id"], kind="debug", title="일 번", tags=["x"])
    add_note(auth_client, subject["id"], kind="review", title="이 번", tags=["x"])
    third = add_note(auth_client, subject["id"], kind="debug", title="삼 번", tags=["x"])
    fourth = add_note(auth_client, subject["id"], kind="debug", title="사 번", tags=["y"])

    body = list_notes(auth_client, subject["id"], {"kind": "debug", "tag": "x"})

    assert ids_of(body) == [third["id"], first["id"]]
    assert fourth["id"] not in ids_of(body)


# --- 페이지 -------------------------------------------------------------------


def test_f4_45개일_때_기본_20개씩_세_페이지로_나뉜다(auth_client):
    subject = create_subject(auth_client)
    created = make_many(auth_client, subject["id"], 45)
    newest_first = [note["id"] for note in reversed(created)]

    page1 = list_notes(auth_client, subject["id"])
    page2 = list_notes(auth_client, subject["id"], {"page": 2})
    page3 = list_notes(auth_client, subject["id"], {"page": 3})

    assert len(page1["items"]) == 20
    assert len(page2["items"]) == 20
    assert len(page3["items"]) == 5
    for number, body in ((1, page1), (2, page2), (3, page3)):
        assert body["total"] == 45
        assert body["page"] == number
        assert body["limit"] == 20
    assert ids_of(page1) == newest_first[:20]
    assert ids_of(page2) == newest_first[20:40]
    assert ids_of(page3) == newest_first[40:]


def test_f4_세_페이지를_합치면_중복도_빠짐도_없다(auth_client):
    subject = create_subject(auth_client)
    created = make_many(auth_client, subject["id"], 45)

    collected = []
    for number in (1, 2, 3):
        collected.extend(ids_of(list_notes(auth_client, subject["id"], {"page": number})))

    assert len(collected) == 45
    assert len(set(collected)) == 45
    assert set(collected) == {note["id"] for note in created}
    assert collected == [note["id"] for note in reversed(created)]


def test_f4_정확히_20개면_한_페이지고_다음_페이지는_비어_있다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 20)

    page1 = list_notes(auth_client, subject["id"])
    page2 = list_notes(auth_client, subject["id"], {"page": 2})

    assert len(page1["items"]) == 20
    assert page1["total"] == 20
    assert page2["items"] == []
    assert page2["total"] == 20


def test_f4_21개면_다음_페이지에_한_개가_온다(auth_client):
    subject = create_subject(auth_client)
    created = make_many(auth_client, subject["id"], 21)

    page1 = list_notes(auth_client, subject["id"])
    page2 = list_notes(auth_client, subject["id"], {"page": 2})

    assert len(page1["items"]) == 20
    assert ids_of(page2) == [created[0]["id"]]
    assert page2["total"] == 21


def test_f4_19개면_한_페이지에_모두_나온다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 19)

    body = list_notes(auth_client, subject["id"])

    assert len(body["items"]) == 19
    assert body["total"] == 19
    assert list_notes(auth_client, subject["id"], {"page": 2})["items"] == []


def test_f4_page가_범위를_넘으면_빈_items와_그대로의_total을_돌려준다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 45)

    body = list_notes(auth_client, subject["id"], {"page": 4})

    assert body["items"] == []
    assert body["total"] == 45
    assert body["page"] == 4
    assert body["limit"] == 20


def test_f4_아주_큰_page도_200과_빈_items다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 3)

    response = auth_client.get(notes_path(subject["id"]), params={"page": str(10**30)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 3


def test_f4_limit을_주면_그_개수씩_나눈다(auth_client):
    subject = create_subject(auth_client)
    created = make_many(auth_client, subject["id"], 12)
    newest_first = [note["id"] for note in reversed(created)]

    page1 = list_notes(auth_client, subject["id"], {"limit": 5})
    page2 = list_notes(auth_client, subject["id"], {"limit": 5, "page": 2})
    page3 = list_notes(auth_client, subject["id"], {"limit": 5, "page": 3})

    assert ids_of(page1) == newest_first[:5]
    assert ids_of(page2) == newest_first[5:10]
    assert ids_of(page3) == newest_first[10:]
    assert page1["limit"] == page2["limit"] == page3["limit"] == 5
    assert page1["total"] == 12


def test_f4_limit_1과_100은_허용된다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 3)

    one = list_notes(auth_client, subject["id"], {"limit": 1})
    hundred = list_notes(auth_client, subject["id"], {"limit": 100})

    assert len(one["items"]) == 1
    assert one["limit"] == 1
    assert one["total"] == 3
    assert len(hundred["items"]) == 3
    assert hundred["limit"] == 100


def test_f4_limit_100이면_101개_중_100개가_나온다(auth_client):
    subject = create_subject(auth_client)
    make_many(auth_client, subject["id"], 101)

    page1 = list_notes(auth_client, subject["id"], {"limit": 100})
    page2 = list_notes(auth_client, subject["id"], {"limit": 100, "page": 2})

    assert len(page1["items"]) == 100
    assert len(page2["items"]) == 1
    assert page1["total"] == 101


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_f4_page가_1_이상의_정수가_아니면_422다(auth_client, value):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"page": value})

    assert_validation_error(response, "page")


@pytest.mark.parametrize("value", ["0", "-1", "101", "1000", "abc", "1.5"])
def test_f4_limit이_1에서_100_사이_정수가_아니면_422다(auth_client, value):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"limit": value})

    assert_validation_error(response, "limit")


def test_f4_page와_limit이_둘_다_잘못되면_fields에_둘_다_있다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"page": "0", "limit": "101"})

    assert_validation_error(response, "page", "limit")


def test_f4_필터가_걸린_상태에서_total은_필터를_적용한_개수다(auth_client):
    subject = create_subject(auth_client)
    for index in range(45):
        add_note(
            auth_client,
            subject["id"],
            kind="debug" if index % 3 == 0 else "remember",
            title=f"노트 {index:02d}",
            is_open=index % 3 == 0,
        )

    open_all = list_notes(auth_client, subject["id"], {"open": "true"})
    open_page2 = list_notes(auth_client, subject["id"], {"open": "true", "limit": 10, "page": 2})
    remember = list_notes(auth_client, subject["id"], {"kind": "remember", "limit": 100})

    assert open_all["total"] == 15
    assert len(open_all["items"]) == 15
    assert open_page2["total"] == 15
    assert len(open_page2["items"]) == 5
    assert remember["total"] == 30
    assert len(remember["items"]) == 30
    unfiltered = list_notes(auth_client, subject["id"])
    assert unfiltered["total"] == 45


def test_f4_필터를_건_결과가_21개_이상이면_20개씩_이어_붙는다(auth_client):
    subject = create_subject(auth_client)
    matching = []
    for index in range(30):
        matching.append(
            add_note(
                auth_client,
                subject["id"],
                kind="debug",
                title=f"일치 {index:02d}",
                tags=["hit"],
                is_open=True,
            )
        )
        add_note(auth_client, subject["id"], kind="remember", title=f"불일치 {index:02d}")

    params = {"kind": "debug", "tag": "hit", "open": "true"}
    page1 = list_notes(auth_client, subject["id"], params)
    page2 = list_notes(auth_client, subject["id"], {**params, "page": 2})
    page3 = list_notes(auth_client, subject["id"], {**params, "page": 3})

    assert len(page1["items"]) == 20
    assert len(page2["items"]) == 10
    assert page3["items"] == []
    assert page1["total"] == page2["total"] == page3["total"] == 30
    assert ids_of(page1) + ids_of(page2) == [note["id"] for note in reversed(matching)]


def test_f4_검색어_결과도_페이지로_나뉜다(auth_client):
    subject = create_subject(auth_client)
    for index in range(25):
        add_note(auth_client, subject["id"], title=f"Match {index:02d}")
        add_note(auth_client, subject["id"], title=f"other {index:02d}", body="nothing")

    page1 = list_notes(auth_client, subject["id"], {"q": "MATCH"})
    page2 = list_notes(auth_client, subject["id"], {"q": "MATCH", "page": 2})

    assert page1["total"] == 25
    assert len(page1["items"]) == 20
    assert len(page2["items"]) == 5
    assert all(title.startswith("Match") for title in titles_of(page1) + titles_of(page2))


# --- 결과 없음 ----------------------------------------------------------------


def test_f4_결과가_없으면_빈_items_total_0과_200이다(auth_client):
    subject = make_and_dataset(auth_client)

    response = auth_client.get(
        notes_path(subject["id"]), params={"kind": "review", "tag": "datetime"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["limit"] == 20
    assert isinstance(body["tags"], list)


# --- 주제 분리·없는 주제·인증 ---------------------------------------------------


def test_f4_다른_주제의_노트는_나오지_않는다(auth_client):
    first = create_subject(auth_client, "주제 하나")
    second = create_subject(auth_client, "주제 둘")
    mine = add_note(auth_client, first["id"], title="isna 하나", tags=["pandas"], is_open=True)
    add_note(auth_client, second["id"], title="isna 둘", tags=["pandas"], is_open=True)
    add_note(auth_client, second["id"], title="다른 주제 노트")

    plain = list_notes(auth_client, first["id"])
    filtered = list_notes(
        auth_client,
        first["id"],
        {"kind": "remember", "tag": "pandas", "q": "isna", "open": "true"},
    )

    assert plain["items"] == [mine]
    assert plain["total"] == 1
    assert filtered["items"] == [mine]
    assert {item["subject_id"] for item in list_notes(auth_client, second["id"])["items"]} == {
        second["id"]
    }


def test_f4_없는_주제의_목록은_404다(auth_client):
    response = auth_client.get(notes_path(9999))

    assert_subject_not_found(response)


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f4_정수가_아니거나_범위_밖인_주제_id는_404다(auth_client, bad_id):
    response = auth_client.get(notes_path(bad_id))

    assert_subject_not_found(response)


def test_f4_로그인하지_않으면_목록은_401이다(client):
    responses = [
        client.get(notes_path(1)),
        client.get(notes_path(1), params={"kind": "debug", "q": "isna"}),
    ]

    for response in responses:
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "unauthorized"


# --- F3 완료 기준 보강: 삭제하면 목록에서 사라진다 -------------------------------------


def test_f4_삭제한_노트는_목록에서_사라지고_total이_줄어든다(auth_client):
    subject = create_subject(auth_client)
    keep = add_note(auth_client, subject["id"], title="남길 노트", tags=["keep"])
    doomed = add_note(auth_client, subject["id"], title="지울 노트", tags=["keep"])
    assert list_notes(auth_client, subject["id"])["total"] == 2

    response = auth_client.delete(note_path(doomed["id"]))
    assert response.status_code == 204, response.text

    body = list_notes(auth_client, subject["id"])
    assert body["total"] == 1
    assert ids_of(body) == [keep["id"]]
    assert_note_not_found(auth_client.get(note_path(doomed["id"])))


def test_f4_삭제한_노트만_가진_태그는_tags에서_빠진다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="남길 노트", tags=["keep", "shared"])
    doomed = add_note(auth_client, subject["id"], title="지울 노트", tags=["only-here", "shared"])
    assert list_notes(auth_client, subject["id"])["tags"] == ["keep", "only-here", "shared"]

    response = auth_client.delete(note_path(doomed["id"]))
    assert response.status_code == 204, response.text

    body = list_notes(auth_client, subject["id"])
    assert body["tags"] == ["keep", "shared"]
    assert list_notes(auth_client, subject["id"], {"tag": "only-here"})["items"] == []


def test_f4_삭제한_노트는_필터_결과에서도_사라진다(auth_client):
    subject = create_subject(auth_client)
    doomed = add_note(
        auth_client, subject["id"], kind="debug", title="isna 오류", tags=["x"], is_open=True
    )
    params = {"kind": "debug", "tag": "x", "q": "isna", "open": "true"}
    assert list_notes(auth_client, subject["id"], params)["total"] == 1

    auth_client.delete(note_path(doomed["id"]))

    body = list_notes(auth_client, subject["id"], params)
    assert body["items"] == []
    assert body["total"] == 0


def test_f4_수정한_태그는_tags_집계와_tag_필터에_반영된다(auth_client):
    subject = create_subject(auth_client)
    note = add_note(auth_client, subject["id"], title="태그 변경", tags=["old"])

    response = auth_client.patch(note_path(note["id"]), json={"tags": ["new"]})
    assert response.status_code == 200, response.text

    assert list_notes(auth_client, subject["id"])["tags"] == ["new"]
    assert list_notes(auth_client, subject["id"], {"tag": "old"})["items"] == []
    assert titles_of(list_notes(auth_client, subject["id"], {"tag": "new"})) == ["태그 변경"]


# --- F4 검증 보강: q와 tag의 길이·개수·NUL 제한 -----------------------------------------

Q_MESSAGE = "검색어는 200자 이내여야 합니다"
TAG_FILTER_MESSAGE = "태그 조건은 최대 20개, 각 1~30자입니다"


def test_f4_q_200자는_200이고_201자는_422다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="a" * 200)

    body = list_notes(auth_client, subject["id"], {"q": "a" * 200})
    assert body["total"] == 1

    response = auth_client.get(notes_path(subject["id"]), params={"q": "a" * 201})
    error = assert_validation_error(response, "q")
    assert error["fields"]["q"] == Q_MESSAGE


def test_f4_q_앞뒤_공백을_뺀_길이가_200자면_200이다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="b" * 200)

    body = list_notes(auth_client, subject["id"], {"q": "  " + "b" * 200 + "  "})
    assert body["total"] == 1


def test_f4_q_공백을_뺀_길이가_201자면_공백이_있어도_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"q": " " + "c" * 201 + " "})
    error = assert_validation_error(response, "q")
    assert error["fields"]["q"] == Q_MESSAGE


def test_f4_q가_아주_길어도_500이_아니라_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(notes_path(subject["id"]), params={"q": "x" * 60000})
    error = assert_validation_error(response, "q")
    assert error["fields"]["q"] == Q_MESSAGE


@pytest.mark.parametrize("raw_query", ["q=%00", "q=a%00b", "q=%00a", "q=a%00"])
def test_f4_q에_NUL_문자가_있으면_422다(auth_client, raw_query):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="ab")

    response = auth_client.get(f"{notes_path(subject['id'])}?{raw_query}")
    assert_validation_error(response, "q")


def test_f4_NUL_문자_422는_다른_조건이_맞아도_바뀌지_않는다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], kind="debug", title="ab", tags=["x"])

    response = auth_client.get(f"{notes_path(subject['id'])}?kind=debug&tag=x&q=a%00b")
    assert_validation_error(response, "q")


def test_f4_tag_20개는_200이고_21개는_422다(auth_client):
    subject = create_subject(auth_client)
    tags = [f"t{i}" for i in range(21)]
    add_note(auth_client, subject["id"], title="태그 많음", tags=tags[:20])

    body = list_notes(auth_client, subject["id"], [("tag", t) for t in tags[:20]])
    assert body["total"] == 1

    response = auth_client.get(notes_path(subject["id"]), params=[("tag", t) for t in tags])
    error = assert_validation_error(response, "tag")
    assert error["fields"]["tag"] == TAG_FILTER_MESSAGE


def test_f4_tag가_1100개여도_500이_아니라_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(
        notes_path(subject["id"]), params=[("tag", f"t{i}") for i in range(1100)]
    )
    error = assert_validation_error(response, "tag")
    assert error["fields"]["tag"] == TAG_FILTER_MESSAGE


def test_f4_tag_30자는_200이고_31자는_422다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="긴 태그", tags=["g" * 30])

    body = list_notes(auth_client, subject["id"], {"tag": "g" * 30})
    assert body["total"] == 1

    response = auth_client.get(notes_path(subject["id"]), params={"tag": "g" * 31})
    error = assert_validation_error(response, "tag")
    assert error["fields"]["tag"] == TAG_FILTER_MESSAGE


def test_f4_tag가_빈_값이면_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(f"{notes_path(subject['id'])}?tag=")
    error = assert_validation_error(response, "tag")
    assert error["fields"]["tag"] == TAG_FILTER_MESSAGE


def test_f4_tag_여러_개_중_하나가_빈_값이거나_31자면_422다(auth_client):
    subject = create_subject(auth_client)
    add_note(auth_client, subject["id"], title="ok", tags=["ok"])

    empty = auth_client.get(f"{notes_path(subject['id'])}?tag=ok&tag=")
    assert_validation_error(empty, "tag")

    too_long = auth_client.get(notes_path(subject["id"]), params=[("tag", "ok"), ("tag", "z" * 31)])
    assert_validation_error(too_long, "tag")
