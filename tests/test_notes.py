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
