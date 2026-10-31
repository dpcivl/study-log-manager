"""F1 학습 주제 관리 계약 테스트.

완료 기준
1. 주제 목록에 생성 최신순으로 모든 주제가 이름·시작일·누적 공부 시간(h)·노트 수·미해결 노트 수와
   함께 표시된다.
2. 이름이 비어 있으면 422로 거부되고 화면에 오류 문구가 보인다.
3. 수정 후 새로고침해도 바뀐 값이 유지된다.

해석
- 공백만 있는 이름은 비어 있는 것으로 보고 422로 거부한다. 그 밖의 이름은 받은 그대로 저장한다.
- PATCH에서 name, background, started_on에 null을 보내면 422다.
  target_date에 null을 보내면 목표일을 지운다.
- 공부 시간·노트 API가 아직 없으므로 계산 필드는 새 주제가 모두 0인지까지만 확인한다.
"""

import re

import pytest
from fastapi.testclient import TestClient

SUBJECT_KEYS = {
    "id",
    "name",
    "background",
    "started_on",
    "target_date",
    "created_at",
    "updated_at",
    "total_minutes",
    "last7_minutes",
    "days_studied",
    "note_count",
    "open_note_count",
}
COMPUTED_KEYS = (
    "total_minutes",
    "last7_minutes",
    "days_studied",
    "note_count",
    "open_note_count",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "주제를 찾을 수 없습니다"},
}
UNSUPPORTED_BODY = {
    "error": {
        "code": "unsupported_media_type",
        "message": "JSON 형식으로 보내야 합니다",
    },
}
VALIDATION_MESSAGE = "입력값을 확인하세요"
NAME_MESSAGE = "이름은 1~100자여야 합니다"


def make_payload(**overrides) -> dict:
    payload = {
        "name": "빅데이터분석기사 실기",
        "background": "임베디드 HW 1년 / SW 2년 5개월",
        "started_on": "2026-10-26",
        "target_date": None,
    }
    payload.update(overrides)
    return payload


def create(client: TestClient, **overrides) -> dict:
    response = client.post("/api/subjects", json=make_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def without(payload: dict, key: str) -> dict:
    return {k: v for k, v in payload.items() if k != key}


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


def assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json() == NOT_FOUND_BODY


# ---------------------------------------------------------------------------
# 완료 기준 1: 목록 (생성 최신순, 표시 필드)
# ---------------------------------------------------------------------------


def test_f1_빈_목록은_빈_items를_돌려준다(auth_client):
    response = auth_client.get("/api/subjects")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"items": []}


def test_f1_목록이_생성_최신순으로_정렬된다(auth_client):
    first = create(auth_client, name="첫 번째")
    second = create(auth_client, name="두 번째")
    third = create(auth_client, name="세 번째")

    response = auth_client.get("/api/subjects")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [third["id"], second["id"], first["id"]]
    assert [item["name"] for item in items] == ["세 번째", "두 번째", "첫 번째"]


def test_f1_같은_초에_만들어도_나중에_만든_주제가_먼저_나온다(auth_client):
    # 연속 생성은 created_at이 같은 초에 찍힐 수 있다. 그래도 순서는 생성 역순이어야 한다.
    ids = [create(auth_client, name=f"주제 {i}")["id"] for i in range(10)]

    items = auth_client.get("/api/subjects").json()["items"]

    assert [item["id"] for item in items] == list(reversed(ids))


def test_f1_목록은_모든_주제를_빠짐없이_보여_준다(auth_client):
    created = [create(auth_client, name=f"주제 {i}") for i in range(25)]

    items = auth_client.get("/api/subjects").json()["items"]

    assert len(items) == 25
    assert {item["id"] for item in items} == {s["id"] for s in created}


def test_f1_목록_항목에_표시용_필드가_모두_있다(auth_client):
    create(auth_client, name="표시 확인", started_on="2026-10-26", target_date="2026-12-06")

    items = auth_client.get("/api/subjects").json()["items"]

    assert len(items) == 1
    item = items[0]
    assert set(item) == SUBJECT_KEYS
    assert item["name"] == "표시 확인"
    assert item["started_on"] == "2026-10-26"
    assert item["target_date"] == "2026-12-06"
    # 누적 공부 시간(분 → 화면에서 h), 노트 수, 미해결 노트 수
    for key in ("total_minutes", "note_count", "open_note_count"):
        assert isinstance(item[key], int)
        assert not isinstance(item[key], bool)


def test_f1_목록_항목은_생성_응답과_같은_모양이다(auth_client):
    created = create(auth_client)

    items = auth_client.get("/api/subjects").json()["items"]

    assert items == [created]


# ---------------------------------------------------------------------------
# 생성 (POST /api/subjects)
# ---------------------------------------------------------------------------


def test_f1_주제를_만들면_201과_전체_필드를_돌려준다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload())

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == SUBJECT_KEYS
    assert isinstance(body["id"], int)
    assert body["name"] == "빅데이터분석기사 실기"
    assert body["background"] == "임베디드 HW 1년 / SW 2년 5개월"
    assert body["started_on"] == "2026-10-26"
    assert body["target_date"] is None


def test_f1_새_주제의_계산_필드는_모두_0이다(auth_client):
    body = create(auth_client)

    for key in COMPUTED_KEYS:
        assert key in body, key
        assert body[key] == 0, key


def test_f1_날짜와_시각은_약속된_형식이다(auth_client):
    body = create(auth_client, target_date="2026-12-06")

    assert DATE_RE.match(body["started_on"])
    assert DATE_RE.match(body["target_date"])
    assert DATETIME_RE.match(body["created_at"]), body["created_at"]
    assert DATETIME_RE.match(body["updated_at"]), body["updated_at"]


def test_f1_서로_다른_주제는_서로_다른_id를_받는다(auth_client):
    a = create(auth_client, name="A")
    b = create(auth_client, name="B")

    assert a["id"] != b["id"]


def test_f1_background와_target_date를_생략해도_만들어진다(auth_client):
    response = auth_client.post(
        "/api/subjects", json={"name": "최소 입력", "started_on": "2026-10-26"}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["background"] == ""
    assert body["target_date"] is None


def test_f1_target_date가_null이어도_만들어진다(auth_client):
    body = create(auth_client, target_date=None)

    assert body["target_date"] is None


def test_f1_target_date를_주면_그대로_저장된다(auth_client):
    body = create(auth_client, target_date="2026-12-06")

    assert body["target_date"] == "2026-12-06"


def test_f1_이름은_받은_그대로_저장된다(auth_client):
    body = create(auth_client, name="  앞뒤 공백 포함  ")

    assert body["name"] == "  앞뒤 공백 포함  "


def test_f1_이름이_100자면_만들어진다(auth_client):
    name = "가" * 100

    body = create(auth_client, name=name)

    assert body["name"] == name


def test_f1_background가_5000자면_만들어진다(auth_client):
    background = "a" * 5000

    body = create(auth_client, background=background)

    assert body["background"] == background


def test_f1_만든_주제를_상세로_다시_읽을_수_있다(auth_client):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.get(f"/api/subjects/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


# ---------------------------------------------------------------------------
# 완료 기준 2: 이름 검증 (422 + 오류 문구)
# ---------------------------------------------------------------------------


def test_f1_이름이_빈_문자열이면_422와_오류_문구를_돌려준다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(name=""))

    error = assert_validation_error(response, "name")
    assert error["fields"]["name"] == NAME_MESSAGE


def test_f1_이름을_보내지_않으면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=without(make_payload(), "name"))

    assert_validation_error(response, "name")


def test_f1_이름이_null이면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(name=None))

    assert_validation_error(response, "name")


@pytest.mark.parametrize("name", [" ", "   ", "\t", "\n", " \t\n "])
def test_f1_이름이_공백만이면_422다(auth_client, name):
    response = auth_client.post("/api/subjects", json=make_payload(name=name))

    error = assert_validation_error(response, "name")
    assert error["fields"]["name"] == NAME_MESSAGE


def test_f1_이름이_101자면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(name="가" * 101))

    error = assert_validation_error(response, "name")
    assert error["fields"]["name"] == NAME_MESSAGE


def test_f1_이름이_문자열이_아니면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(name=123))

    assert_validation_error(response, "name")


def test_f1_이름_검증에_실패하면_주제가_만들어지지_않는다(auth_client):
    auth_client.post("/api/subjects", json=make_payload(name=""))
    auth_client.post("/api/subjects", json=make_payload(name="가" * 101))

    assert auth_client.get("/api/subjects").json() == {"items": []}


# ---------------------------------------------------------------------------
# 그 밖의 입력 검증
# ---------------------------------------------------------------------------


def test_f1_시작일을_보내지_않으면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=without(make_payload(), "started_on"))

    assert_validation_error(response, "started_on")


def test_f1_시작일이_null이면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(started_on=None))

    assert_validation_error(response, "started_on")


@pytest.mark.parametrize(
    "value",
    ["", "abc", "2026/10/26", "26-10-26", "2026-13-01", "2026-02-30", "20261026", 20261026],
)
def test_f1_시작일_형식이_틀리면_422다(auth_client, value):
    response = auth_client.post("/api/subjects", json=make_payload(started_on=value))

    assert_validation_error(response, "started_on")


@pytest.mark.parametrize("value", ["", "abc", "2026/12/06", "2026-13-01", "2026-02-30"])
def test_f1_목표일_형식이_틀리면_422다(auth_client, value):
    response = auth_client.post("/api/subjects", json=make_payload(target_date=value))

    assert_validation_error(response, "target_date")


def test_f1_background가_5001자면_422다(auth_client):
    response = auth_client.post("/api/subjects", json=make_payload(background="a" * 5001))

    assert_validation_error(response, "background")


def test_f1_여러_필드가_틀리면_fields에_모두_담긴다(auth_client):
    response = auth_client.post("/api/subjects", json={"name": "", "started_on": "not-a-date"})

    assert_validation_error(response, "name", "started_on")


def test_f1_검증에_실패해도_오류_본문은_error_모양이다(auth_client):
    response = auth_client.post("/api/subjects", json={})

    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) <= {"code", "message", "fields"}


# ---------------------------------------------------------------------------
# 415: JSON이 아닌 본문
# ---------------------------------------------------------------------------


def test_f1_POST가_JSON이_아니면_415다(auth_client):
    response = auth_client.post(
        "/api/subjects",
        content="name=abc&started_on=2026-10-26",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert auth_client.get("/api/subjects").json() == {"items": []}


def test_f1_POST의_Content_Type이_text_plain이면_415다(auth_client):
    response = auth_client.post(
        "/api/subjects",
        content='{"name": "x", "started_on": "2026-10-26"}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY


def test_f1_PATCH가_JSON이_아니면_415다(auth_client):
    created = create(auth_client)

    response = auth_client.patch(
        f"/api/subjects/{created['id']}",
        content="name=바꿈",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["name"] == created["name"]


# ---------------------------------------------------------------------------
# 상세 (GET /api/subjects/{id})
# ---------------------------------------------------------------------------


def test_f1_상세는_주제_하나를_계산_필드와_함께_돌려준다(auth_client):
    created = create(auth_client, name="상세 확인", target_date="2026-12-06")

    response = auth_client.get(f"/api/subjects/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUBJECT_KEYS
    assert body["id"] == created["id"]
    assert body["name"] == "상세 확인"
    for key in COMPUTED_KEYS:
        assert body[key] == 0, key


def test_f1_상세는_요청한_id의_주제만_돌려준다(auth_client):
    a = create(auth_client, name="A")
    b = create(auth_client, name="B")

    assert auth_client.get(f"/api/subjects/{a['id']}").json()["name"] == "A"
    assert auth_client.get(f"/api/subjects/{b['id']}").json()["name"] == "B"


def test_f1_없는_id를_조회하면_404다(auth_client):
    response = auth_client.get("/api/subjects/9999")

    assert_not_found(response)


def test_f1_빈_DB에서_id_1을_조회하면_404다(auth_client):
    assert_not_found(auth_client.get("/api/subjects/1"))


# ---------------------------------------------------------------------------
# 완료 기준 3: 수정 (PATCH /api/subjects/{id})
# ---------------------------------------------------------------------------


def test_f1_PATCH로_target_date만_바꾸면_나머지는_유지된다(auth_client):
    created = create(auth_client, name="유지 확인", background="배경 메모", target_date=None)

    response = auth_client.patch(
        f"/api/subjects/{created['id']}", json={"target_date": "2026-12-06"}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == SUBJECT_KEYS
    assert body["target_date"] == "2026-12-06"
    assert body["name"] == "유지 확인"
    assert body["background"] == "배경 메모"
    assert body["started_on"] == "2026-10-26"
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]


def test_f1_PATCH로_이름만_바꾸면_나머지는_유지된다(auth_client):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "새 이름"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "새 이름"
    assert body["background"] == created["background"]
    assert body["started_on"] == created["started_on"]
    assert body["target_date"] == "2026-12-06"


def test_f1_PATCH로_여러_필드를_한_번에_바꾼다(auth_client):
    created = create(auth_client)

    response = auth_client.patch(
        f"/api/subjects/{created['id']}",
        json={
            "name": "바뀐 이름",
            "background": "바뀐 배경",
            "started_on": "2026-11-01",
            "target_date": "2027-01-15",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "바뀐 이름"
    assert body["background"] == "바뀐 배경"
    assert body["started_on"] == "2026-11-01"
    assert body["target_date"] == "2027-01-15"


def test_f1_수정_후_다시_읽어도_바뀐_값이_유지된다(auth_client):
    created = create(auth_client)
    patch = auth_client.patch(
        f"/api/subjects/{created['id']}",
        json={"name": "새로고침 후에도", "background": "유지", "target_date": "2026-12-06"},
    )
    assert patch.status_code == 200

    detail = auth_client.get(f"/api/subjects/{created['id']}").json()
    listed = auth_client.get("/api/subjects").json()["items"]

    assert detail["name"] == "새로고침 후에도"
    assert detail["background"] == "유지"
    assert detail["target_date"] == "2026-12-06"
    assert detail["started_on"] == "2026-10-26"
    assert listed == [detail]


def test_f1_PATCH_응답과_이후_상세_조회가_같다(auth_client):
    created = create(auth_client)

    patched = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "일치 확인"}).json()
    detail = auth_client.get(f"/api/subjects/{created['id']}").json()

    assert patched == detail


def test_f1_PATCH는_updated_at_형식을_지키고_created_at을_바꾸지_않는다(auth_client):
    created = create(auth_client)

    body = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "시각"}).json()

    assert DATETIME_RE.match(body["updated_at"]), body["updated_at"]
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] >= created["updated_at"]


def test_f1_PATCH로_target_date를_null로_보내면_목표일이_지워진다(auth_client):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"target_date": None})

    assert response.status_code == 200
    assert response.json()["target_date"] is None
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["target_date"] is None


def test_f1_PATCH에서_보내지_않은_target_date는_지워지지_않는다(auth_client):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "다른 필드"})

    assert response.json()["target_date"] == "2026-12-06"


def test_f1_PATCH로_background를_빈_문자열로_비울_수_있다(auth_client):
    created = create(auth_client, background="지울 내용")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"background": ""})

    assert response.status_code == 200
    assert response.json()["background"] == ""
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["background"] == ""


def test_f1_빈_객체로_PATCH하면_아무것도_바뀌지_않는다(auth_client):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={})

    assert response.status_code == 200
    body = response.json()
    for key in ("id", "name", "background", "started_on", "target_date", "created_at"):
        assert body[key] == created[key], key


def test_f1_PATCH는_다른_주제에_영향을_주지_않는다(auth_client):
    a = create(auth_client, name="A")
    b = create(auth_client, name="B")

    auth_client.patch(f"/api/subjects/{a['id']}", json={"name": "A2"})

    assert auth_client.get(f"/api/subjects/{b['id']}").json()["name"] == "B"


def test_f1_PATCH로_이름을_빈_문자열로_바꾸면_422이고_값이_유지된다(auth_client):
    created = create(auth_client, name="지켜야 할 이름")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": ""})

    error = assert_validation_error(response, "name")
    assert error["fields"]["name"] == NAME_MESSAGE
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["name"] == "지켜야 할 이름"


@pytest.mark.parametrize("name", [" ", "   ", "\t\n"])
def test_f1_PATCH로_이름을_공백만으로_바꾸면_422다(auth_client, name):
    created = create(auth_client, name="지켜야 할 이름")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": name})

    assert_validation_error(response, "name")
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["name"] == "지켜야 할 이름"


def test_f1_PATCH로_이름을_101자로_바꾸면_422다(auth_client):
    created = create(auth_client)

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "가" * 101})

    assert_validation_error(response, "name")


def test_f1_PATCH로_이름을_100자로_바꾸면_200이다(auth_client):
    created = create(auth_client)

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"name": "가" * 100})

    assert response.status_code == 200
    assert response.json()["name"] == "가" * 100


@pytest.mark.parametrize("field", ["name", "background", "started_on"])
def test_f1_PATCH에서_필수_필드에_null을_보내면_422다(auth_client, field):
    created = create(auth_client)

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={field: None})

    assert_validation_error(response, field)
    assert auth_client.get(f"/api/subjects/{created['id']}").json()[field] == created[field]


@pytest.mark.parametrize("value", ["", "abc", "2026/11/01", "2026-02-30"])
def test_f1_PATCH로_시작일_형식이_틀리면_422다(auth_client, value):
    created = create(auth_client)

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"started_on": value})

    assert_validation_error(response, "started_on")
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["started_on"] == "2026-10-26"


@pytest.mark.parametrize("value", ["", "abc", "2026/12/06", "2026-13-01"])
def test_f1_PATCH로_목표일_형식이_틀리면_422다(auth_client, value):
    created = create(auth_client, target_date="2026-12-06")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"target_date": value})

    assert_validation_error(response, "target_date")
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["target_date"] == "2026-12-06"


def test_f1_PATCH로_background를_5001자로_바꾸면_422다(auth_client):
    created = create(auth_client, background="원래 배경")

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"background": "a" * 5001})

    assert_validation_error(response, "background")
    assert auth_client.get(f"/api/subjects/{created['id']}").json()["background"] == "원래 배경"


def test_f1_PATCH로_background를_5000자로_바꾸면_200이다(auth_client):
    created = create(auth_client)

    response = auth_client.patch(f"/api/subjects/{created['id']}", json={"background": "a" * 5000})

    assert response.status_code == 200
    assert response.json()["background"] == "a" * 5000


def test_f1_없는_id를_PATCH하면_404다(auth_client):
    response = auth_client.patch("/api/subjects/9999", json={"name": "없는 주제"})

    assert_not_found(response)


def test_f1_없는_id_PATCH가_주제를_만들지_않는다(auth_client):
    auth_client.patch("/api/subjects/9999", json={"name": "없는 주제"})

    assert auth_client.get("/api/subjects").json() == {"items": []}


# ---------------------------------------------------------------------------
# 화면 (로그인 후 200)
# ---------------------------------------------------------------------------


def test_f1_로그인_후_S2_목록_화면이_200이다(auth_client):
    response = auth_client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f1_주제가_있어도_S2_목록_화면이_200이다(auth_client):
    create(auth_client)

    response = auth_client.get("/", follow_redirects=False)

    assert response.status_code == 200


def test_f1_로그인_후_S3_상세_화면이_200이다(auth_client):
    created = create(auth_client)

    response = auth_client.get(f"/subjects/{created['id']}", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# ---------------------------------------------------------------------------
# 로그인 없이 호출
# ---------------------------------------------------------------------------


def test_f1_로그인하지_않으면_주제_API가_401이다(client):
    body = {
        "error": {"code": "unauthorized", "message": "로그인이 필요합니다"},
    }

    responses = [
        client.get("/api/subjects"),
        client.post("/api/subjects", json=make_payload()),
        client.get("/api/subjects/1"),
        client.patch("/api/subjects/1", json={"name": "x"}),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json() == body
