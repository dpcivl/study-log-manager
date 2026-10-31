"""F2 공부 시간 기록 계약 테스트.

완료 기준
1. 기록 추가 직후 목록 맨 위(날짜 최신순)에 나타나고 누적 합계가 그만큼 늘어난다.
2. 최근 7일 합계는 오늘 포함 7일(KST) 안의 기록만 더한다.
3. 수정해 저장하면 바뀐 값이 목록과 합계에 즉시 반영된다.
4. 삭제하면 목록과 합계에서 즉시 빠진다.
5. 분이 1 미만이거나 1440 초과면 422다.

해석
- 목록은 항상 studied_on 내림차순, 같은 날은 id 내림차순이다. "목록 맨 위"는 가장 최근 날짜로
  추가했을 때의 결과이며, 지난 날짜를 추가하면 날짜 순서 자리에 들어간다.
- 미래 날짜도 저장할 수 있다. 다만 최근 7일 합계에는 들어가지 않는다
  (오늘 포함 7일은 KST 오늘-6일 ~ 오늘).
- PATCH에서 studied_on, minutes, memo에 null을 보내면 422다.
  minutes는 정수만 받는다(60.5, "60", true는 422).
- minutes의 15 단위는 화면 입력 편의이며 API는 1~1440 정수를 모두 받는다.
- page는 1 이상, limit은 1~100 정수다. 벗어나면 422 validation_error다(100으로 잘라 주지 않는다).
- API 경로의 id가 정수가 아니거나 범위 밖이면 없는 자원으로 보고 404다.
- 빈 객체로 PATCH하면 200이고 아무것도 바뀌지 않는다.
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

SESSION_KEYS = {"id", "subject_id", "studied_on", "minutes", "memo", "created_at"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

SUBJECT_NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "주제를 찾을 수 없습니다"},
}
SESSION_NOT_FOUND_BODY = {
    "error": {"code": "not_found", "message": "기록을 찾을 수 없습니다"},
}
UNSUPPORTED_BODY = {
    "error": {
        "code": "unsupported_media_type",
        "message": "JSON 형식으로 보내야 합니다",
    },
}
VALIDATION_MESSAGE = "입력값을 확인하세요"
MINUTES_MESSAGE = "1~1440 사이여야 합니다"

BAD_IDS = ["abc", "0", "-1", str(2**63), str(2**64)]
BAD_MINUTES = [0, -1, 1441, 100000, 60.5, "60", "", "abc", True, False, None, [], {}]
BAD_DATES = [
    "",
    "abc",
    "2026/10/31",
    "26-10-31",
    "2026-13-01",
    "2026-02-30",
    "20261031",
    20261031,
    None,
]


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def days_from_today(offset: int) -> str:
    return (today_kst() + timedelta(days=offset)).isoformat()


def create_subject(client: TestClient, name: str = "빅데이터분석기사 실기") -> dict:
    response = client.post(
        "/api/subjects",
        json={"name": name, "background": "", "started_on": "2026-10-26"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_session(
    client: TestClient,
    subject_id: int,
    studied_on: str = "2026-10-29",
    minutes: int = 60,
    **extra,
) -> dict:
    payload = {"studied_on": studied_on, "minutes": minutes, **extra}
    response = client.post(f"/api/subjects/{subject_id}/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def sessions_path(subject_id) -> str:
    return f"/api/subjects/{subject_id}/sessions"


def list_sessions(client: TestClient, subject_id: int, query: str = "") -> dict:
    response = client.get(sessions_path(subject_id) + query)
    assert response.status_code == 200, response.text
    return response.json()


def subject_stats(client: TestClient, subject_id: int) -> dict:
    """주제 상세와 주제 목록의 계산 필드가 같은지 확인하고 돌려준다."""
    keys = ("total_minutes", "last7_minutes", "days_studied")
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


def assert_stats(
    client: TestClient,
    subject_id: int,
    *,
    total: int,
    last7: int,
    days: int,
) -> None:
    assert subject_stats(client, subject_id) == {
        "total_minutes": total,
        "last7_minutes": last7,
        "days_studied": days,
    }
    assert list_sessions(client, subject_id)["total_minutes"] == total


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


def assert_subject_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json() == SUBJECT_NOT_FOUND_BODY


def assert_session_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json() == SESSION_NOT_FOUND_BODY


# ---------------------------------------------------------------------------
# 완료 기준 1: 추가 직후 목록 맨 위, 누적 합계 증가
# ---------------------------------------------------------------------------


def test_f2_기록을_추가하면_201과_StudySession_모양을_돌려준다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": 90, "memo": "groupby 연습"},
    )

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == SESSION_KEYS
    assert isinstance(body["id"], int)
    assert body["subject_id"] == subject["id"]
    assert body["studied_on"] == "2026-10-31"
    assert body["minutes"] == 90
    assert body["memo"] == "groupby 연습"
    assert DATETIME_RE.match(body["created_at"]), body["created_at"]


def test_f2_memo를_생략하면_빈_문자열로_저장된다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": 30},
    )

    assert response.status_code == 201
    assert response.json()["memo"] == ""
    assert list_sessions(auth_client, subject["id"])["items"][0]["memo"] == ""


def test_f2_빈_주제의_목록은_빈_items와_합계_0이다(auth_client):
    subject = create_subject(auth_client)

    body = list_sessions(auth_client, subject["id"])

    assert body == {"items": [], "total": 0, "page": 1, "limit": 20, "total_minutes": 0}
    assert_stats(auth_client, subject["id"], total=0, last7=0, days=0)


def test_f2_목록_항목은_StudySession_모양이고_목록_응답에_페이지_정보가_있다(auth_client):
    subject = create_subject(auth_client)
    add_session(auth_client, subject["id"], "2026-10-28", 60, memo="시나공 ch3")

    body = list_sessions(auth_client, subject["id"])

    assert set(body) == {"items", "total", "page", "limit", "total_minutes"}
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["limit"] == 20
    item = body["items"][0]
    assert set(item) == SESSION_KEYS
    assert DATE_RE.match(item["studied_on"])
    assert DATETIME_RE.match(item["created_at"])
    assert item["memo"] == "시나공 ch3"


def test_f2_기록을_추가하면_목록_맨_위에_나타난다(auth_client):
    subject = create_subject(auth_client)
    add_session(auth_client, subject["id"], days_from_today(-2), 30)

    created = add_session(auth_client, subject["id"], days_from_today(0), 45, memo="방금")

    body = list_sessions(auth_client, subject["id"])
    assert body["items"][0] == created
    assert body["total"] == 2


def test_f2_기록을_추가하면_누적_합계가_그만큼_늘어난다(auth_client):
    subject = create_subject(auth_client)
    today = days_from_today(0)

    add_session(auth_client, subject["id"], today, 60)
    assert_stats(auth_client, subject["id"], total=60, last7=60, days=1)

    add_session(auth_client, subject["id"], days_from_today(-1), 90)
    assert_stats(auth_client, subject["id"], total=150, last7=150, days=2)

    add_session(auth_client, subject["id"], days_from_today(-2), 15)
    assert_stats(auth_client, subject["id"], total=165, last7=165, days=3)


def test_f2_지난_날짜를_추가하면_날짜_순서_자리에_들어간다(auth_client):
    subject = create_subject(auth_client)
    newest = add_session(auth_client, subject["id"], "2026-10-30", 10)
    oldest = add_session(auth_client, subject["id"], "2026-10-26", 20)

    middle = add_session(auth_client, subject["id"], "2026-10-28", 30)

    items = list_sessions(auth_client, subject["id"])["items"]
    assert [item["id"] for item in items] == [newest["id"], middle["id"], oldest["id"]]
    assert [item["studied_on"] for item in items] == ["2026-10-30", "2026-10-28", "2026-10-26"]


def test_f2_목록이_studied_on_내림차순으로_정렬된다(auth_client):
    subject = create_subject(auth_client)
    # 날짜 순서와 입력 순서가 어긋나도록 섞어서 넣는다.
    for studied_on in ["2026-10-27", "2026-10-31", "2026-10-26", "2026-10-29", "2026-10-28"]:
        add_session(auth_client, subject["id"], studied_on, 10)

    items = list_sessions(auth_client, subject["id"])["items"]

    assert [item["studied_on"] for item in items] == [
        "2026-10-31",
        "2026-10-29",
        "2026-10-28",
        "2026-10-27",
        "2026-10-26",
    ]


def test_f2_같은_날_기록은_id_내림차순이다(auth_client):
    subject = create_subject(auth_client)
    first = add_session(auth_client, subject["id"], "2026-10-29", 10)
    other_day = add_session(auth_client, subject["id"], "2026-10-30", 5)
    second = add_session(auth_client, subject["id"], "2026-10-29", 20)
    third = add_session(auth_client, subject["id"], "2026-10-29", 30)

    items = list_sessions(auth_client, subject["id"])["items"]

    assert [item["id"] for item in items] == [
        other_day["id"],
        third["id"],
        second["id"],
        first["id"],
    ]


def test_f2_같은_날_두_기록은_days_studied에서_1일로_센다(auth_client):
    subject = create_subject(auth_client)
    today = days_from_today(0)

    add_session(auth_client, subject["id"], today, 60)
    add_session(auth_client, subject["id"], today, 30)

    assert_stats(auth_client, subject["id"], total=90, last7=90, days=1)

    add_session(auth_client, subject["id"], days_from_today(-1), 10)
    assert_stats(auth_client, subject["id"], total=100, last7=100, days=2)


def test_f2_합계는_주제끼리_섞이지_않는다(auth_client):
    a = create_subject(auth_client, "A")
    b = create_subject(auth_client, "B")
    empty = create_subject(auth_client, "C")
    today = days_from_today(0)

    add_session(auth_client, a["id"], today, 60)
    add_session(auth_client, a["id"], days_from_today(-1), 40)
    add_session(auth_client, b["id"], today, 25)

    assert_stats(auth_client, a["id"], total=100, last7=100, days=2)
    assert_stats(auth_client, b["id"], total=25, last7=25, days=1)
    assert_stats(auth_client, empty["id"], total=0, last7=0, days=0)
    assert [item["minutes"] for item in list_sessions(auth_client, a["id"])["items"]] == [60, 40]
    assert [item["minutes"] for item in list_sessions(auth_client, b["id"])["items"]] == [25]
    assert list_sessions(auth_client, empty["id"])["items"] == []


def test_f2_다른_주제의_기록_수정과_삭제는_이_주제_합계에_영향을_주지_않는다(auth_client):
    a = create_subject(auth_client, "A")
    b = create_subject(auth_client, "B")
    today = days_from_today(0)
    add_session(auth_client, a["id"], today, 60)
    b_session = add_session(auth_client, b["id"], today, 25)

    auth_client.patch(f"/api/sessions/{b_session['id']}", json={"minutes": 100})
    assert_stats(auth_client, a["id"], total=60, last7=60, days=1)
    assert_stats(auth_client, b["id"], total=100, last7=100, days=1)

    auth_client.delete(f"/api/sessions/{b_session['id']}")
    assert_stats(auth_client, a["id"], total=60, last7=60, days=1)
    assert_stats(auth_client, b["id"], total=0, last7=0, days=0)


def test_f2_미래_날짜도_저장할_수_있다(auth_client):
    subject = create_subject(auth_client)

    created = add_session(auth_client, subject["id"], days_from_today(30), 60)

    assert list_sessions(auth_client, subject["id"])["items"][0]["id"] == created["id"]
    assert_stats(auth_client, subject["id"], total=60, last7=0, days=1)


# ---------------------------------------------------------------------------
# 완료 기준 2: 최근 7일 합계 (오늘 포함 7일, KST)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [0, -1, -3, -6])
def test_f2_최근_7일_합계에_오늘부터_6일_전까지_기록이_들어간다(auth_client, offset):
    subject = create_subject(auth_client)

    add_session(auth_client, subject["id"], days_from_today(offset), 50)

    assert_stats(auth_client, subject["id"], total=50, last7=50, days=1)


@pytest.mark.parametrize("offset", [-7, -8, -30, -365, 1, 2, 30])
def test_f2_최근_7일_합계에_7일_전_이전과_내일_이후_기록은_들어가지_않는다(auth_client, offset):
    subject = create_subject(auth_client)

    add_session(auth_client, subject["id"], days_from_today(offset), 50)

    assert_stats(auth_client, subject["id"], total=50, last7=0, days=1)


def test_f2_최근_7일_경계를_오늘_6일_전_7일_전_내일_기록으로_확인한다(auth_client):
    subject = create_subject(auth_client)
    add_session(auth_client, subject["id"], days_from_today(0), 1)
    add_session(auth_client, subject["id"], days_from_today(-6), 10)
    add_session(auth_client, subject["id"], days_from_today(-7), 100)
    add_session(auth_client, subject["id"], days_from_today(1), 1000)

    assert_stats(auth_client, subject["id"], total=1111, last7=11, days=4)


def test_f2_최근_7일_합계는_같은_날_여러_기록을_모두_더한다(auth_client):
    subject = create_subject(auth_client)
    for _ in range(3):
        add_session(auth_client, subject["id"], days_from_today(-6), 20)
    add_session(auth_client, subject["id"], days_from_today(-7), 20)

    assert_stats(auth_client, subject["id"], total=80, last7=60, days=2)


def test_f2_수정으로_날짜를_옮기면_최근_7일_합계가_바뀐다(auth_client):
    subject = create_subject(auth_client)
    old = add_session(auth_client, subject["id"], days_from_today(-7), 40)
    assert_stats(auth_client, subject["id"], total=40, last7=0, days=1)

    response = auth_client.patch(
        f"/api/sessions/{old['id']}", json={"studied_on": days_from_today(-6)}
    )
    assert response.status_code == 200
    assert_stats(auth_client, subject["id"], total=40, last7=40, days=1)

    response = auth_client.patch(
        f"/api/sessions/{old['id']}", json={"studied_on": days_from_today(1)}
    )
    assert response.status_code == 200
    assert_stats(auth_client, subject["id"], total=40, last7=0, days=1)


def test_f2_삭제하면_최근_7일_합계에서도_빠진다(auth_client):
    subject = create_subject(auth_client)
    keep = add_session(auth_client, subject["id"], days_from_today(0), 10)
    drop = add_session(auth_client, subject["id"], days_from_today(-6), 20)
    add_session(auth_client, subject["id"], days_from_today(-7), 30)
    assert_stats(auth_client, subject["id"], total=60, last7=30, days=3)

    assert auth_client.delete(f"/api/sessions/{drop['id']}").status_code == 204

    assert_stats(auth_client, subject["id"], total=40, last7=10, days=2)
    assert keep["id"] in [i["id"] for i in list_sessions(auth_client, subject["id"])["items"]]


# ---------------------------------------------------------------------------
# 완료 기준 3: 수정이 목록과 합계에 즉시 반영
# ---------------------------------------------------------------------------


def test_f2_수정하면_200과_바뀐_StudySession을_돌려준다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 120, memo="처음")

    response = auth_client.patch(
        f"/api/sessions/{created['id']}",
        json={"studied_on": "2026-10-30", "minutes": 60, "memo": "고침"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == SESSION_KEYS
    assert body["id"] == created["id"]
    assert body["subject_id"] == subject["id"]
    assert body["studied_on"] == "2026-10-30"
    assert body["minutes"] == 60
    assert body["memo"] == "고침"
    assert body["created_at"] == created["created_at"]


def test_f2_수정한_값이_목록에_즉시_반영된다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 120, memo="처음")

    auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": 60, "memo": "고침"})

    items = list_sessions(auth_client, subject["id"])["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["minutes"] == 60
    assert items[0]["memo"] == "고침"
    assert items[0]["studied_on"] == "2026-10-29"


def test_f2_수정한_분이_누적_합계에_즉시_반영된다(auth_client):
    subject = create_subject(auth_client)
    today = days_from_today(0)
    target = add_session(auth_client, subject["id"], today, 120)
    add_session(auth_client, subject["id"], days_from_today(-1), 30)
    assert_stats(auth_client, subject["id"], total=150, last7=150, days=2)

    auth_client.patch(f"/api/sessions/{target['id']}", json={"minutes": 60})
    assert_stats(auth_client, subject["id"], total=90, last7=90, days=2)

    auth_client.patch(f"/api/sessions/{target['id']}", json={"minutes": 500})
    assert_stats(auth_client, subject["id"], total=530, last7=530, days=2)


def test_f2_수정으로_날짜를_바꾸면_목록_순서와_days_studied가_바뀐다(auth_client):
    subject = create_subject(auth_client)
    a = add_session(auth_client, subject["id"], "2026-10-26", 10)
    b = add_session(auth_client, subject["id"], "2026-10-28", 20)
    c = add_session(auth_client, subject["id"], "2026-10-30", 30)

    auth_client.patch(f"/api/sessions/{a['id']}", json={"studied_on": "2026-10-31"})

    items = list_sessions(auth_client, subject["id"])["items"]
    assert [item["id"] for item in items] == [a["id"], c["id"], b["id"]]

    # 같은 날로 옮기면 days_studied가 줄어든다.
    auth_client.patch(f"/api/sessions/{b['id']}", json={"studied_on": "2026-10-31"})
    assert subject_stats(auth_client, subject["id"])["days_studied"] == 2
    assert subject_stats(auth_client, subject["id"])["total_minutes"] == 60


def test_f2_PATCH는_보낸_필드만_수정한다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 120, memo="유지될 메모")

    only_minutes = auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": 45}).json()
    assert only_minutes["studied_on"] == "2026-10-29"
    assert only_minutes["memo"] == "유지될 메모"
    assert only_minutes["minutes"] == 45

    only_date = auth_client.patch(
        f"/api/sessions/{created['id']}", json={"studied_on": "2026-10-30"}
    ).json()
    assert only_date["minutes"] == 45
    assert only_date["memo"] == "유지될 메모"
    assert only_date["studied_on"] == "2026-10-30"

    only_memo = auth_client.patch(f"/api/sessions/{created['id']}", json={"memo": "새 메모"}).json()
    assert only_memo["minutes"] == 45
    assert only_memo["studied_on"] == "2026-10-30"
    assert only_memo["memo"] == "새 메모"


def test_f2_PATCH로_memo를_빈_문자열로_비울_수_있다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 60, memo="지울 메모")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"memo": ""})

    assert response.status_code == 200
    assert response.json()["memo"] == ""
    assert list_sessions(auth_client, subject["id"])["items"][0]["memo"] == ""


def test_f2_빈_객체로_PATCH하면_아무것도_바뀌지_않는다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 120, memo="그대로")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json() == created
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


def test_f2_PATCH는_다른_기록에_영향을_주지_않는다(auth_client):
    subject = create_subject(auth_client)
    a = add_session(auth_client, subject["id"], "2026-10-29", 10, memo="A")
    b = add_session(auth_client, subject["id"], "2026-10-29", 20, memo="B")

    auth_client.patch(f"/api/sessions/{a['id']}", json={"minutes": 99, "memo": "A2"})

    items = {item["id"]: item for item in list_sessions(auth_client, subject["id"])["items"]}
    assert items[b["id"]] == b


@pytest.mark.parametrize("minutes", [1, 1440])
def test_f2_PATCH로_분을_경계값_1과_1440으로_바꿀_수_있다(auth_client, minutes):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 60)

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": minutes})

    assert response.status_code == 200
    assert response.json()["minutes"] == minutes
    assert list_sessions(auth_client, subject["id"])["total_minutes"] == minutes


# ---------------------------------------------------------------------------
# 완료 기준 4: 삭제가 목록과 합계에 즉시 반영
# ---------------------------------------------------------------------------


def test_f2_삭제하면_204와_빈_본문을_돌려준다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])

    response = auth_client.delete(f"/api/sessions/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""


def test_f2_삭제하면_목록에서_즉시_빠진다(auth_client):
    subject = create_subject(auth_client)
    keep = add_session(auth_client, subject["id"], "2026-10-28", 10)
    drop = add_session(auth_client, subject["id"], "2026-10-29", 20)

    auth_client.delete(f"/api/sessions/{drop['id']}")

    body = list_sessions(auth_client, subject["id"])
    assert [item["id"] for item in body["items"]] == [keep["id"]]
    assert body["total"] == 1


def test_f2_삭제하면_누적_합계와_days_studied에서_즉시_빠진다(auth_client):
    subject = create_subject(auth_client)
    today = days_from_today(0)
    add_session(auth_client, subject["id"], today, 60)
    drop = add_session(auth_client, subject["id"], days_from_today(-1), 40)
    assert_stats(auth_client, subject["id"], total=100, last7=100, days=2)

    auth_client.delete(f"/api/sessions/{drop['id']}")

    assert_stats(auth_client, subject["id"], total=60, last7=60, days=1)


def test_f2_같은_날_기록_하나를_지워도_다른_기록이_있으면_days_studied는_1이다(auth_client):
    subject = create_subject(auth_client)
    today = days_from_today(0)
    add_session(auth_client, subject["id"], today, 60)
    drop = add_session(auth_client, subject["id"], today, 30)

    auth_client.delete(f"/api/sessions/{drop['id']}")

    assert_stats(auth_client, subject["id"], total=60, last7=60, days=1)


def test_f2_모든_기록을_지우면_합계가_0으로_돌아간다(auth_client):
    subject = create_subject(auth_client)
    created = [add_session(auth_client, subject["id"], days_from_today(-i), 10) for i in range(3)]

    for session in created:
        assert auth_client.delete(f"/api/sessions/{session['id']}").status_code == 204

    assert list_sessions(auth_client, subject["id"])["items"] == []
    assert_stats(auth_client, subject["id"], total=0, last7=0, days=0)


def test_f2_삭제한_뒤_같은_id로_PATCH하면_404다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])
    auth_client.delete(f"/api/sessions/{created['id']}")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": 10})

    assert_session_not_found(response)


def test_f2_삭제한_뒤_같은_id로_DELETE하면_404다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])
    assert auth_client.delete(f"/api/sessions/{created['id']}").status_code == 204

    response = auth_client.delete(f"/api/sessions/{created['id']}")

    assert_session_not_found(response)


def test_f2_기록을_지워도_주제는_남는다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])

    auth_client.delete(f"/api/sessions/{created['id']}")

    assert auth_client.get(f"/api/subjects/{subject['id']}").status_code == 200


# ---------------------------------------------------------------------------
# 완료 기준 5: 분 범위 검증 (1..1440 정수)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [1, 7, 15, 90, 1439, 1440])
def test_f2_분이_1에서_1440_사이의_정수면_저장된다(auth_client, minutes):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": minutes},
    )

    assert response.status_code == 201
    assert response.json()["minutes"] == minutes
    assert list_sessions(auth_client, subject["id"])["total_minutes"] == minutes


@pytest.mark.parametrize("minutes", [0, -1, 1441])
def test_f2_분이_1_미만이거나_1440_초과면_422이고_fields_minutes_문구가_붙는다(
    auth_client, minutes
):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": minutes},
    )

    error = assert_validation_error(response, "minutes")
    assert error["fields"]["minutes"] == MINUTES_MESSAGE


@pytest.mark.parametrize("minutes", BAD_MINUTES)
def test_f2_정수가_아니거나_범위_밖인_분은_POST에서_422다(auth_client, minutes):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": minutes},
    )

    assert_validation_error(response, "minutes")
    assert list_sessions(auth_client, subject["id"])["total"] == 0
    assert_stats(auth_client, subject["id"], total=0, last7=0, days=0)


def test_f2_분을_빼고_보내면_POST는_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(sessions_path(subject["id"]), json={"studied_on": "2026-10-31"})

    assert_validation_error(response, "minutes")
    assert list_sessions(auth_client, subject["id"])["total"] == 0


@pytest.mark.parametrize("minutes", BAD_MINUTES)
def test_f2_정수가_아니거나_범위_밖인_분은_PATCH에서_422이고_값이_유지된다(auth_client, minutes):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], days_from_today(0), 120, memo="그대로")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": minutes})

    assert_validation_error(response, "minutes")
    assert list_sessions(auth_client, subject["id"])["items"] == [created]
    assert_stats(auth_client, subject["id"], total=120, last7=120, days=1)


@pytest.mark.parametrize("minutes", [0, 1441])
def test_f2_PATCH의_범위_오류_문구도_같다(auth_client, minutes):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"minutes": minutes})

    error = assert_validation_error(response, "minutes")
    assert error["fields"]["minutes"] == MINUTES_MESSAGE


def test_f2_검증_오류_본문은_error_모양이고_retry_after가_없다(auth_client):
    subject = create_subject(auth_client)

    body = auth_client.post(sessions_path(subject["id"]), json={}).json()

    assert set(body) == {"error"}
    assert set(body["error"]) <= {"code", "message", "fields"}


# ---------------------------------------------------------------------------
# 그 밖의 입력 검증: 날짜, 메모
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("studied_on", BAD_DATES)
def test_f2_날짜_형식이_틀리면_POST는_422다(auth_client, studied_on):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": studied_on, "minutes": 60},
    )

    assert_validation_error(response, "studied_on")
    assert list_sessions(auth_client, subject["id"])["total"] == 0


def test_f2_날짜를_빼고_보내면_POST는_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(sessions_path(subject["id"]), json={"minutes": 60})

    assert_validation_error(response, "studied_on")
    assert list_sessions(auth_client, subject["id"])["total"] == 0


def test_f2_날짜와_분이_모두_틀리면_fields에_둘_다_담긴다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "abc", "minutes": 0},
    )

    assert_validation_error(response, "studied_on", "minutes")


@pytest.mark.parametrize("studied_on", BAD_DATES)
def test_f2_날짜가_틀리거나_null이면_PATCH는_422이고_값이_유지된다(auth_client, studied_on):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 60)

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"studied_on": studied_on})

    assert_validation_error(response, "studied_on")
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


@pytest.mark.parametrize("length", [0, 1, 500])
def test_f2_메모는_500자까지_저장된다(auth_client, length):
    subject = create_subject(auth_client)
    memo = "가" * length

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": 60, "memo": memo},
    )

    assert response.status_code == 201
    assert response.json()["memo"] == memo
    assert list_sessions(auth_client, subject["id"])["items"][0]["memo"] == memo


def test_f2_메모가_501자면_POST는_422다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        json={"studied_on": "2026-10-31", "minutes": 60, "memo": "가" * 501},
    )

    assert_validation_error(response, "memo")
    assert list_sessions(auth_client, subject["id"])["total"] == 0


def test_f2_PATCH로_메모를_500자까지_바꿀_수_있다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"])

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"memo": "나" * 500})

    assert response.status_code == 200
    assert response.json()["memo"] == "나" * 500


def test_f2_메모가_501자면_PATCH는_422이고_값이_유지된다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], memo="유지")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"memo": "가" * 501})

    assert_validation_error(response, "memo")
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


def test_f2_PATCH에서_memo가_null이면_422다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], memo="유지")

    response = auth_client.patch(f"/api/sessions/{created['id']}", json={"memo": None})

    assert_validation_error(response, "memo")
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


def test_f2_검증에_실패한_PATCH는_다른_필드도_바꾸지_않는다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 60, memo="유지")

    response = auth_client.patch(
        f"/api/sessions/{created['id']}",
        json={"studied_on": "2026-10-30", "memo": "바뀌면 안 됨", "minutes": 0},
    )

    assert_validation_error(response, "minutes")
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


# ---------------------------------------------------------------------------
# 404: 없는 주제, 없는 기록, 잘못된 id
# ---------------------------------------------------------------------------


def test_f2_없는_주제의_목록은_404다(auth_client):
    assert_subject_not_found(auth_client.get(sessions_path(9999)))


def test_f2_없는_주제에_기록을_추가하면_404다(auth_client):
    response = auth_client.post(
        sessions_path(9999),
        json={"studied_on": "2026-10-31", "minutes": 60},
    )

    assert_subject_not_found(response)


def test_f2_없는_기록을_수정하면_404다(auth_client):
    assert_session_not_found(auth_client.patch("/api/sessions/9999", json={"minutes": 10}))


def test_f2_없는_기록을_삭제하면_404다(auth_client):
    assert_session_not_found(auth_client.delete("/api/sessions/9999"))


def test_f2_주제_id를_기록_id_자리에_써도_404다(auth_client):
    subject = create_subject(auth_client)
    # 주제는 1개, 기록은 0개이므로 같은 숫자의 기록은 존재하지 않는다.
    assert_session_not_found(auth_client.delete(f"/api/sessions/{subject['id']}"))


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f2_정수가_아니거나_범위_밖인_주제_id의_목록은_404다(auth_client, bad_id):
    assert_subject_not_found(auth_client.get(sessions_path(bad_id)))


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f2_정수가_아니거나_범위_밖인_주제_id에_추가하면_404다(auth_client, bad_id):
    response = auth_client.post(
        sessions_path(bad_id),
        json={"studied_on": "2026-10-31", "minutes": 60},
    )

    assert_subject_not_found(response)


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f2_정수가_아니거나_범위_밖인_기록_id의_PATCH는_404다(auth_client, bad_id):
    response = auth_client.patch(f"/api/sessions/{bad_id}", json={"minutes": 10})

    assert_session_not_found(response)


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_f2_정수가_아니거나_범위_밖인_기록_id의_DELETE는_404다(auth_client, bad_id):
    assert_session_not_found(auth_client.delete(f"/api/sessions/{bad_id}"))


# ---------------------------------------------------------------------------
# 페이지
# ---------------------------------------------------------------------------


def _seed_25(client: TestClient) -> tuple[dict, list[dict]]:
    subject = create_subject(client)
    base = date(2026, 10, 1)
    created = [
        add_session(client, subject["id"], (base + timedelta(days=i)).isoformat(), i + 1)
        for i in range(25)
    ]
    return subject, created


def test_f2_limit_기본값은_20이고_둘째_페이지에_나머지_5개가_있다(auth_client):
    subject, created = _seed_25(auth_client)
    newest_first = [s["id"] for s in reversed(created)]

    first = list_sessions(auth_client, subject["id"])
    second = list_sessions(auth_client, subject["id"], "?page=2")

    assert first["total"] == 25
    assert first["page"] == 1
    assert first["limit"] == 20
    assert [item["id"] for item in first["items"]] == newest_first[:20]
    assert second["total"] == 25
    assert second["page"] == 2
    assert second["limit"] == 20
    assert [item["id"] for item in second["items"]] == newest_first[20:]
    assert len(second["items"]) == 5


def test_f2_total_minutes는_페이지와_무관하게_전체_합계다(auth_client):
    subject, _ = _seed_25(auth_client)
    expected = sum(range(1, 26))

    assert list_sessions(auth_client, subject["id"])["total_minutes"] == expected
    assert list_sessions(auth_client, subject["id"], "?page=2")["total_minutes"] == expected
    assert list_sessions(auth_client, subject["id"], "?limit=3")["total_minutes"] == expected
    assert list_sessions(auth_client, subject["id"], "?page=9")["total_minutes"] == expected
    assert subject_stats(auth_client, subject["id"])["total_minutes"] == expected


def test_f2_page가_범위를_넘으면_빈_items와_그대로의_total을_돌려준다(auth_client):
    subject, _ = _seed_25(auth_client)

    body = list_sessions(auth_client, subject["id"], "?page=3")

    assert body["items"] == []
    assert body["total"] == 25
    assert body["page"] == 3
    assert body["limit"] == 20


def test_f2_limit과_page로_원하는_크기로_나눠_볼_수_있다(auth_client):
    subject, created = _seed_25(auth_client)
    newest_first = [s["id"] for s in reversed(created)]

    body = list_sessions(auth_client, subject["id"], "?limit=5&page=2")

    assert body["limit"] == 5
    assert body["page"] == 2
    assert [item["id"] for item in body["items"]] == newest_first[5:10]


def test_f2_limit_최대값_100은_허용된다(auth_client):
    subject, _ = _seed_25(auth_client)

    body = list_sessions(auth_client, subject["id"], "?limit=100")

    assert body["limit"] == 100
    assert len(body["items"]) == 25


def test_f2_limit_1은_허용된다(auth_client):
    subject, created = _seed_25(auth_client)

    body = list_sessions(auth_client, subject["id"], "?limit=1")

    assert [item["id"] for item in body["items"]] == [created[-1]["id"]]
    assert body["total"] == 25


def test_f2_같은_날_여러_기록은_페이지를_넘어도_id_내림차순이다(auth_client):
    subject = create_subject(auth_client)
    created = [add_session(auth_client, subject["id"], "2026-10-29", i + 1) for i in range(6)]
    expected = [s["id"] for s in reversed(created)]

    page1 = list_sessions(auth_client, subject["id"], "?limit=4&page=1")["items"]
    page2 = list_sessions(auth_client, subject["id"], "?limit=4&page=2")["items"]

    assert [item["id"] for item in page1 + page2] == expected


@pytest.mark.parametrize(
    "query",
    [
        "?page=0",
        "?page=-1",
        "?page=abc",
        "?page=1.5",
        "?page=",
        "?limit=0",
        "?limit=-1",
        "?limit=101",
        "?limit=1000",
        "?limit=abc",
        "?limit=2.5",
        "?limit=",
    ],
)
def test_f2_page_limit이_범위를_벗어나거나_정수가_아니면_422다(auth_client, query):
    subject = create_subject(auth_client)
    add_session(auth_client, subject["id"])

    response = auth_client.get(sessions_path(subject["id"]) + query)

    assert_validation_error(response)


def test_f2_limit_101은_100으로_잘라_주지_않는다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.get(sessions_path(subject["id"]) + "?limit=101")

    assert response.status_code == 422
    assert "items" not in response.json()


# ---------------------------------------------------------------------------
# 415: JSON이 아닌 본문
# ---------------------------------------------------------------------------


def test_f2_POST가_JSON이_아니면_415다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        content="studied_on=2026-10-31&minutes=60",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert list_sessions(auth_client, subject["id"])["total"] == 0


def test_f2_POST의_Content_Type이_text_plain이면_415다(auth_client):
    subject = create_subject(auth_client)

    response = auth_client.post(
        sessions_path(subject["id"]),
        content='{"studied_on": "2026-10-31", "minutes": 60}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert list_sessions(auth_client, subject["id"])["total"] == 0


def test_f2_PATCH가_JSON이_아니면_415다(auth_client):
    subject = create_subject(auth_client)
    created = add_session(auth_client, subject["id"], "2026-10-29", 60)

    response = auth_client.patch(
        f"/api/sessions/{created['id']}",
        content="minutes=10",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY
    assert list_sessions(auth_client, subject["id"])["items"] == [created]


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------


def test_f2_로그인하지_않으면_모든_기록_API가_401이다(client):
    responses = [
        client.get(sessions_path(1)),
        client.post(sessions_path(1), json={"studied_on": "2026-10-31", "minutes": 60}),
        client.patch("/api/sessions/1", json={"minutes": 10}),
        client.delete("/api/sessions/1"),
    ]

    for response in responses:
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "unauthorized"
