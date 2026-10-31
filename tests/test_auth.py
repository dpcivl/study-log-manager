"""F5 비밀번호 로그인 계약 테스트.

완료 기준
1. 로그인하지 않은 상태에서 /api/* 호출은 401, 화면 주소는 /login으로 이동한다.
2. 올바른 비밀번호로 로그인하면 S2로 이동하고 브라우저를 닫았다 열어도 30일 안에는 유지된다.
3. 틀린 비밀번호 5회 연속이면 60초 동안 429로 거부된다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import TEST_PASSWORD, make_settings

UNAUTHORIZED_BODY = {
    "error": {"code": "unauthorized", "message": "로그인이 필요합니다"},
}
INVALID_PASSWORD_BODY = {
    "error": {"code": "invalid_password", "message": "비밀번호가 올바르지 않습니다"},
}
THIRTY_DAYS = 2592000
REDIRECT_CODES = (302, 303, 307)

# 5절 표의 로그인·로그아웃을 제외한 모든 API
PROTECTED_API = [
    ("GET", "/api/subjects", None),
    ("POST", "/api/subjects", {"name": "x", "started_on": "2026-10-01"}),
    ("GET", "/api/subjects/1", None),
    ("PATCH", "/api/subjects/1", {"name": "y"}),
    ("GET", "/api/subjects/1/sessions", None),
    ("POST", "/api/subjects/1/sessions", {"studied_on": "2026-10-01", "minutes": 30}),
    ("PATCH", "/api/sessions/1", {"minutes": 45}),
    ("DELETE", "/api/sessions/1", None),
    ("POST", "/api/subjects/1/notes", {"kind": "remember", "title": "t"}),
    ("GET", "/api/notes/1", None),
    ("PATCH", "/api/notes/1", {"title": "t2"}),
    ("DELETE", "/api/notes/1", None),
    ("GET", "/api/subjects/1/notes", None),
    ("GET", "/api/subjects/1/export", None),
]

# 로그인하지 않으면 /login으로 보내야 하는 화면 주소
PROTECTED_PAGES = [
    "/",
    "/subjects/1",
    "/subjects/1/notes/new",
    "/notes/1",
    "/notes/1/edit",
]


def _ids(items):
    return [f"{m} {p}" if isinstance(p, str) else str(p) for m, p, _ in items]


def call(client: TestClient, method: str, path: str, body=None, **kwargs):
    if body is not None:
        kwargs["json"] = body
    return client.request(method, path, **kwargs)


def session_set_cookie(response) -> str:
    """응답에서 session 쿠키를 설정하는 Set-Cookie 헤더 한 줄을 돌려준다."""
    lines = [h for h in response.headers.get_list("set-cookie") if h.lower().startswith("session=")]
    assert len(lines) == 1, response.headers.get_list("set-cookie")
    return lines[0]


def cookie_attrs(header: str) -> dict[str, str]:
    """`session=v; Path=/; HttpOnly` -> {"session": "v", "path": "/", "httponly": ""}"""
    attrs: dict[str, str] = {}
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        attrs[key.lower()] = value.strip().strip('"')
    return attrs


def login(client: TestClient, password: str = TEST_PASSWORD):
    return client.post("/api/login", json={"password": password})


def assert_unauthorized(response):
    assert response.status_code == 401, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == UNAUTHORIZED_BODY


# ---------------------------------------------------------------------------
# 완료 기준 1: 미로그인 /api/* 는 401, 화면 주소는 /login 으로 이동
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_API, ids=_ids(PROTECTED_API))
def test_f5_미로그인_데이터_API는_401_unauthorized(client, method, path, body):
    assert_unauthorized(call(client, method, path, body))


def test_f5_미로그인_401_응답은_fields와_retry_after가_없다(client):
    error = client.get("/api/subjects").json()["error"]
    assert "fields" not in error
    assert "retry_after" not in error


@pytest.mark.parametrize("cookie", ["garbage", "a.b.c", ""], ids=["문자열", "점구분", "빈값"])
def test_f5_엉터리_session_쿠키는_401(client, cookie):
    response = client.get("/api/subjects", headers={"Cookie": f"session={cookie}"})
    assert_unauthorized(response)


def test_f5_변조한_session_쿠키는_401(auth_client):
    token = auth_client.cookies.get("session")
    assert token
    # 마지막 글자는 base64에서 쓰이지 않는 비트가 있어 바꿔도 디코딩 결과가 같을 수 있다.
    # 항상 값이 바뀌도록 끝에서 두 번째 글자를 바꾼다.
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    response = TestClient(auth_client.app).get(
        "/api/subjects", headers={"Cookie": f"session={tampered}"}
    )
    assert_unauthorized(response)


def test_f5_다른_SECRET_KEY로_서명된_쿠키는_401(client):
    other_app = create_app(make_settings(secret_key="another-secret-key"))
    with TestClient(other_app) as other:
        assert login(other).status_code == 204
        foreign_token = other.cookies.get("session")
    assert foreign_token
    response = client.get("/api/subjects", headers={"Cookie": f"session={foreign_token}"})
    assert_unauthorized(response)


@pytest.mark.parametrize("path", PROTECTED_PAGES)
def test_f5_미로그인_화면_주소는_302로_login_이동(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("path", PROTECTED_PAGES)
def test_f5_엉터리_쿠키로_화면_주소를_열어도_login_이동(client, path):
    response = client.get(path, headers={"Cookie": "session=garbage"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_f5_미로그인_화면_주소를_따라가면_로그인_화면이_보인다(client):
    response = client.get("/")
    assert response.status_code == 200
    assert str(response.url).endswith("/login")
    assert response.headers["content-type"].startswith("text/html")


def test_f5_미로그인이어도_login_화면은_그대로_표시된다(client):
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# ---------------------------------------------------------------------------
# 완료 기준 2: 올바른 비밀번호로 로그인하면 S2로 이동, 30일 유지
# ---------------------------------------------------------------------------


def test_f5_올바른_비밀번호는_204_본문없음(client):
    response = login(client)
    assert response.status_code == 204
    assert response.content == b""


def test_f5_로그인_응답에_session_쿠키_속성이_붙는다(client):
    header = session_set_cookie(login(client))
    attrs = cookie_attrs(header)
    assert attrs["session"] != ""
    assert attrs["max-age"] == str(THIRTY_DAYS)
    assert attrs["path"] == "/"
    assert "httponly" in attrs
    assert attrs["samesite"].lower() == "lax"
    # 테스트 서버는 HTTP이므로 Secure는 붙지 않는다.
    assert "secure" not in attrs


def test_f5_세션_토큰에_비밀번호가_들어있지_않다(client):
    token = cookie_attrs(session_set_cookie(login(client)))["session"]
    assert TEST_PASSWORD not in token


def test_f5_로그인_후_쿠키로_데이터_API가_401이_아니다(auth_client):
    # 데이터 API 본문은 다른 기능의 몫이므로 인증을 통과했는지(401이 아닌지)만 본다.
    assert auth_client.cookies.get("session")
    response = auth_client.get("/api/subjects")
    assert response.status_code != 401


def test_f5_로그인_후_S2_화면이_200(auth_client):
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f5_로그인_상태에서_login_화면은_루트로_이동(auth_client):
    response = auth_client.get("/login", follow_redirects=False)
    assert response.status_code in REDIRECT_CODES
    assert response.headers["location"] == "/"


def test_f5_브라우저를_닫았다_열어도_같은_쿠키로_로그인_상태가_유지된다(auth_client):
    token = auth_client.cookies.get("session")
    assert token
    # 브라우저 재시작: 같은 서버(같은 설정), 쿠키 저장소만 새로 시작하되 저장된 쿠키만 다시 보냄.
    with TestClient(auth_client.app) as reopened:
        header = {"Cookie": f"session={token}"}
        assert reopened.get("/api/subjects", headers=header).status_code != 401
        page = reopened.get("/", headers=header, follow_redirects=False)
        assert page.status_code == 200


def test_f5_같은_설정의_새_서버_프로세스에서도_쿠키가_유효하다(auth_client, settings):
    # 서버 저장이 없는 서명 쿠키이므로 앱을 다시 만들어도(재시작) 유지된다.
    token = auth_client.cookies.get("session")
    with TestClient(create_app(settings)) as restarted:
        response = restarted.get("/api/subjects", headers={"Cookie": f"session={token}"})
        assert response.status_code != 401


def test_f5_로그인을_두번_해도_성공한다(auth_client):
    assert login(auth_client).status_code == 204


@pytest.mark.parametrize(
    "password",
    [TEST_PASSWORD + "x", TEST_PASSWORD[:-1], TEST_PASSWORD.upper(), " " + TEST_PASSWORD, "wrong"],
    ids=["뒤에글자", "한글자모자람", "대문자", "앞공백", "전혀다름"],
)
def test_f5_틀린_비밀번호는_401_invalid_password(client, password):
    response = login(client, password)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == INVALID_PASSWORD_BODY
    assert not any(
        h.lower().startswith("session=") and cookie_attrs(h)["session"]
        for h in response.headers.get_list("set-cookie")
    )


def test_f5_틀린_비밀번호_후에도_데이터_API는_401(client):
    login(client, "wrong")
    assert_unauthorized(client.get("/api/subjects"))


# ---------------------------------------------------------------------------
# 로그아웃
# ---------------------------------------------------------------------------


def test_f5_로그아웃은_204와_쿠키_삭제_헤더(auth_client):
    response = auth_client.post("/api/logout")
    assert response.status_code == 204
    assert response.content == b""
    attrs = cookie_attrs(session_set_cookie(response))
    assert attrs["session"] == ""
    assert attrs["max-age"] == "0"


def test_f5_로그아웃_뒤에는_데이터_API가_401(auth_client):
    auth_client.post("/api/logout")
    assert_unauthorized(auth_client.get("/api/subjects"))


def test_f5_로그아웃_뒤에는_화면_주소가_login으로_이동(auth_client):
    auth_client.post("/api/logout")
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_f5_로그아웃_뒤_다시_로그인할_수_있다(auth_client):
    auth_client.post("/api/logout")
    assert login(auth_client).status_code == 204
    assert auth_client.get("/api/subjects").status_code != 401


def test_f5_로그인_안_한_채_로그아웃해도_204(client):
    response = client.post("/api/logout")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# 완료 기준 3: 틀린 비밀번호 5회 연속이면 429
# ---------------------------------------------------------------------------


def test_f5_틀린_비밀번호_5회까지는_401_6번째는_429(client):
    for attempt in range(1, 6):
        response = login(client, "wrong")
        assert response.status_code == 401, f"{attempt}번째 시도"
    response = login(client, "wrong")
    assert response.status_code == 429


def test_f5_429_응답은_too_many_attempts_모양이고_retry_after가_붙는다(client):
    for _ in range(5):
        login(client, "wrong")
    response = login(client, "wrong")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert error["code"] == "too_many_attempts"
    assert error["message"] == "잠시 후 다시 시도하세요"
    assert isinstance(error["retry_after"], int)
    assert 0 < error["retry_after"] <= 60
    assert "fields" not in error


def test_f5_잠긴_동안에는_올바른_비밀번호도_429이고_쿠키가_발급되지_않는다(client):
    for _ in range(5):
        login(client, "wrong")
    response = login(client, TEST_PASSWORD)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert response.headers.get_list("set-cookie") == []
    assert_unauthorized(client.get("/api/subjects"))


def test_f5_잠긴_상태가_이어지는_동안_계속_429(client):
    for _ in range(5):
        login(client, "wrong")
    for _ in range(3):
        assert login(client, "wrong").status_code == 429


def test_f5_4회_실패_뒤_올바른_비밀번호는_성공한다(client):
    for _ in range(4):
        assert login(client, "wrong").status_code == 401
    assert login(client, TEST_PASSWORD).status_code == 204


def test_f5_로그인에_성공하면_실패_횟수가_초기화된다(client):
    for _ in range(4):
        assert login(client, "wrong").status_code == 401
    assert login(client, TEST_PASSWORD).status_code == 204
    # 초기화됐다면 다시 5번 틀려야 잠긴다.
    for attempt in range(1, 6):
        assert login(client, "wrong").status_code == 401, f"{attempt}번째 시도"
    assert login(client, "wrong").status_code == 429


def test_f5_연속_실패만_센다_중간에_성공이_끼면_이어지지_않는다(client):
    for _ in range(3):
        login(client, "wrong")
    assert login(client, TEST_PASSWORD).status_code == 204
    for _ in range(3):
        login(client, "wrong")
    # 성공 전 3 + 후 3 = 6회 실패지만 연속이 아니므로 잠기지 않는다.
    assert login(client, TEST_PASSWORD).status_code == 204


def test_f5_새_앱_인스턴스는_실패_횟수가_초기화된_상태다(settings):
    # 테스트 간 격리 확인: 실패 횟수는 서버 메모리에 있으므로 앱마다 따로다.
    with TestClient(create_app(settings)) as first:
        for _ in range(5):
            login(first, "wrong")
        assert login(first, "wrong").status_code == 429
    with TestClient(create_app(settings)) as second:
        assert login(second, TEST_PASSWORD).status_code == 204


# ---------------------------------------------------------------------------
# 415: 본문이 있는 POST는 JSON만
# ---------------------------------------------------------------------------

UNSUPPORTED_BODY = {
    "error": {"code": "unsupported_media_type", "message": "JSON 형식으로 보내야 합니다"},
}


def test_f5_로그인에_form_본문을_보내면_415(client):
    response = client.post("/api/login", data={"password": TEST_PASSWORD})
    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == UNSUPPORTED_BODY


def test_f5_로그인에_text_plain_본문을_보내면_415(client):
    response = client.post(
        "/api/login",
        content=f'{{"password": "{TEST_PASSWORD}"}}',
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_BODY


def test_f5_415_요청으로는_로그인되지_않는다(client):
    client.post("/api/login", data={"password": TEST_PASSWORD})
    assert_unauthorized(client.get("/api/subjects"))


def test_f5_JSON_charset_Content_Type은_허용된다(client):
    response = client.post(
        "/api/login",
        content=f'{{"password": "{TEST_PASSWORD}"}}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# 완료 기준 3 (동시 요청): 동시에 틀려도 5회 연속 실패 뒤에는 429
# ---------------------------------------------------------------------------

CONCURRENT_REQUESTS = 30
MAX_FAILURES_BEFORE_LOCK = 5


def test_f5_틀린_비밀번호를_동시에_보내도_401은_5개까지이고_나머지는_429(client):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as pool:
        futures = [pool.submit(login, client, "wrong") for _ in range(CONCURRENT_REQUESTS)]
        responses = [future.result() for future in futures]

    statuses = [response.status_code for response in responses]
    assert set(statuses) <= {401, 429}, statuses

    unauthorized = [r for r in responses if r.status_code == 401]
    too_many = [r for r in responses if r.status_code == 429]
    assert len(unauthorized) <= MAX_FAILURES_BEFORE_LOCK, statuses
    assert len(unauthorized) + len(too_many) == CONCURRENT_REQUESTS

    for response in unauthorized:
        assert response.json() == INVALID_PASSWORD_BODY
    for response in too_many:
        error = response.json()["error"]
        assert error["code"] == "too_many_attempts"
        assert error["message"] == "잠시 후 다시 시도하세요"
        assert 0 < error["retry_after"] <= 60

    # 동시 요청이 끝난 뒤에는 잠긴 상태이므로 올바른 비밀번호도 429이고 쿠키가 발급되지 않는다.
    after = login(client, TEST_PASSWORD)
    assert after.status_code == 429
    assert after.json()["error"]["code"] == "too_many_attempts"
    assert after.headers.get_list("set-cookie") == []
    assert_unauthorized(client.get("/api/subjects"))


# ---------------------------------------------------------------------------
# 리뷰 라운드 1: 짝 없는 서로게이트 이스케이프(\ud800) 비밀번호
# ---------------------------------------------------------------------------

_SURROGATE_LOGIN = dict(
    content='{"password":"\\ud800"}',
    headers={"Content-Type": "application/json"},
)


def test_f5_짝_없는_서로게이트_비밀번호는_401_invalid_password다(client):
    response = client.post("/api/login", **_SURROGATE_LOGIN)

    assert response.status_code == 401, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == INVALID_PASSWORD_BODY


def test_f5_짝_없는_서로게이트_비밀번호도_실패_횟수에_들어가_6번째는_429다(client):
    for attempt in range(1, 6):
        response = client.post("/api/login", **_SURROGATE_LOGIN)
        assert response.status_code == 401, (attempt, response.text)
        assert response.json() == INVALID_PASSWORD_BODY

    response = client.post("/api/login", **_SURROGATE_LOGIN)

    assert response.status_code == 429, response.text
