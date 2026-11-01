"""SEC-1 ~ SEC-4 보안 계약 테스트.

완료 기준
SEC-1. PUBLIC_DEPLOY가 켜져 있을 때 SECRET_KEY나 APP_PASSWORD가 비었거나, 공백뿐이거나,
       최소 길이(SECRET_KEY 32자, APP_PASSWORD 12자, 앞뒤 공백을 뺀 길이)보다 짧으면 앱이
       시작되지 않는다. 기준을 만족하면 지금과 같이 시작한다. 꺼져 있으면 시작은 하되 약한
       값이면 경고를 로그에 남긴다. 로그에 값 자체는 남기지 않는다.
SEC-2. 1MiB(1048576바이트)보다 큰 본문을 보낸 POST·PATCH는 로그인 여부와 무관하게 공통 오류
       모양(413 payload_too_large)으로 거부되고 핸들러에 닿지 않는다. 상한 이하의 가장 큰
       정상 노트(본문 50,000자)는 저장된다. password가 1024자를 넘으면 비교 없이 401로
       거부되고 실패 횟수에 들어간다.
SEC-3. 공개 배포용 설정을 켜면 프록시 헤더가 없는 요청에도 로그인 응답의 Set-Cookie에 Secure가
       붙는다. 설정을 끈 로컬 실행에서는 지금처럼 http로 로그인된다(https 요청에는 Secure).
       로그아웃 쿠키도 같은 속성을 쓴다.
SEC-4. X-Forwarded-For를 바꿔도 같은 잠금 카운터가 쓰여 6번째 시도가 429다.
SEC-5. 입력 처리(제어 문자·날짜·잘못된 UTF-8), 화면 주소, 로그아웃 CSRF,
       잠금 단위(IPv6 /64, 추적 상한).
SEC-6. 보안 헤더, no-store, HSTS, 인라인 스크립트·스타일 금지, 문서 주소 끔,
       405·500 모양, 보호 목록 자동 검사.
"""

import asyncio
import ipaddress
import itertools
import json
import logging
import re
import string
import time

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.auth import LoginRateLimiter, rate_limit_key
from app.body_limit import MAX_BODY_BYTES, BodySizeLimitMiddleware
from app.main import create_app

from .conftest import TEST_PASSWORD, make_settings

MAX_BODY = 1048576  # 1MiB
JSON_HEADERS = {"Content-Type": "application/json"}

PAYLOAD_TOO_LARGE_BODY = {
    "error": {"code": "payload_too_large", "message": "요청 본문이 너무 큽니다"},
}
INVALID_PASSWORD_BODY = {
    "error": {"code": "invalid_password", "message": "비밀번호가 올바르지 않습니다"},
}

STRONG_KEY = "k" * 40
STRONG_PASSWORD = "correct-horse-battery"  # 21자


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def start_app(**overrides):
    """설정을 만들고 앱을 한 번 열었다 닫는다. 시작이 막히면 예외가 난다."""
    app = create_app(make_settings(**overrides))
    with TestClient(app):
        pass


def json_body_of_size(size: int, filler_key: str, **fields) -> bytes:
    """정확히 size 바이트인 JSON 본문을 만든다. filler_key 필드를 'a'로 채운다."""
    base = json.dumps({**fields, filler_key: ""}, separators=(",", ":")).encode()
    padding = size - len(base)
    assert padding >= 0
    body = json.dumps({**fields, filler_key: "a" * padding}, separators=(",", ":")).encode()
    assert len(body) == size
    return body


def chunks(body: bytes, step: int = 64 * 1024):
    """Content-Length 없이(chunked) 보내기 위한 제너레이터."""
    for i in range(0, len(body), step):
        yield body[i : i + step]


def assert_payload_too_large(response):
    assert response.status_code == 413, response.text[:200]
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == PAYLOAD_TOO_LARGE_BODY


def assert_invalid_password(response):
    assert response.status_code == 401, response.text[:200]
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == INVALID_PASSWORD_BODY


def create_subject(client: TestClient, name: str = "보안 테스트") -> int:
    response = client.post("/api/subjects", json={"name": name, "started_on": "2026-10-01"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# 본문 상한을 확인할 4개 엔드포인트. (이름, 메서드, 주소 템플릿, 채울 필드, 나머지 필드)
OVERSIZE_TARGETS = [
    pytest.param("POST", "/api/login", "password", {}, id="POST_login"),
    pytest.param(
        "POST",
        "/api/subjects",
        "background",
        {"name": "x", "started_on": "2026-10-01"},
        id="POST_subjects",
    ),
    pytest.param("PATCH", "/api/subjects/{sid}", "background", {}, id="PATCH_subject"),
    pytest.param(
        "POST",
        "/api/subjects/{sid}/notes",
        "body",
        {"kind": "remember", "title": "t"},
        id="POST_notes",
    ),
]
LOGIN_STATES = ["anon", "auth"]


@pytest.fixture
def prepared(request):
    """(client, subject_id)를 돌려준다. 로그인 상태에 따라 미로그인/로그인 클라이언트."""
    state = request.param
    client = request.getfixturevalue("auth_client" if state == "auth" else "client")
    # 미로그인에는 주제를 만들 수 없으므로 존재하지 않는 id를 쓴다. 핸들러에 닿기 전에 막혀야 한다.
    subject_id = create_subject(client) if state == "auth" else 1
    return client, subject_id


# ---------------------------------------------------------------------------
# SEC-1: 공개 배포에서 약한 SECRET_KEY / APP_PASSWORD
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("secret_key", "app_password"),
    [
        pytest.param("k" * 31, STRONG_PASSWORD, id="키_31자"),
        pytest.param(STRONG_KEY, "p" * 11, id="비밀번호_11자"),
        pytest.param("", STRONG_PASSWORD, id="키_빈값"),
        pytest.param(STRONG_KEY, "", id="비밀번호_빈값"),
        pytest.param(" " * 40, STRONG_PASSWORD, id="키_공백_40자"),
        pytest.param(STRONG_KEY, " " * 20, id="비밀번호_공백_20자"),
        pytest.param("", "", id="둘다_빈값"),
        # 앞뒤 공백을 뺀 길이로 센다.
        pytest.param("a" + " " * 40, STRONG_PASSWORD, id="키_a_뒤_공백_40자"),
        pytest.param(STRONG_KEY, "a" + " " * 20, id="비밀번호_a_뒤_공백_20자"),
        pytest.param(" " + "k" * 31 + " ", STRONG_PASSWORD, id="키_공백_포함_34자_실제_31자"),
        pytest.param(STRONG_KEY, " " + "p" * 11 + " ", id="비밀번호_공백_포함_14자_실제_11자"),
    ],
)
def test_sec1_공개_배포에서_약한_값이면_앱이_시작되지_않는다(secret_key, app_password):
    with pytest.raises(RuntimeError):
        start_app(public_deploy=True, secret_key=secret_key, app_password=app_password)


def test_sec1_공개_배포에서_앞뒤_공백을_뺀_길이가_기준을_채우면_시작된다():
    start_app(
        public_deploy=True,
        secret_key=" " + "k" * 32 + " ",
        app_password="  " + "p" * 12 + "  ",
    )


def test_sec1_공개_배포에서_경계값_키_32자_비밀번호_12자는_시작되고_로그인된다():
    key = "k" * 32
    password = "p" * 12
    app = create_app(make_settings(public_deploy=True, secret_key=key, app_password=password))
    # 공개 배포에서는 쿠키가 항상 Secure이므로 https 클라이언트로 확인한다. (SEC-3 해석)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/login", json={"password": password}).status_code == 204
        assert client.get("/api/subjects").status_code == 200


def test_sec1_공개_배포에서_충분히_강한_값은_시작되고_틀린_비밀번호는_401():
    app = create_app(
        make_settings(public_deploy=True, secret_key=STRONG_KEY, app_password=STRONG_PASSWORD)
    )
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": STRONG_PASSWORD}).status_code == 204
        assert_invalid_password(client.post("/api/login", json={"password": "wrong-password"}))


def test_sec1_공개_배포에서_키만_경계값_바로_아래면_시작되지_않는다():
    # 비밀번호가 충분히 길어도 키 하나만 31자면 막힌다.
    with pytest.raises(RuntimeError):
        start_app(public_deploy=True, secret_key="k" * 31, app_password="p" * 12)


def test_sec1_공개_배포에서_비밀번호만_경계값_바로_아래면_시작되지_않는다():
    with pytest.raises(RuntimeError):
        start_app(public_deploy=True, secret_key="k" * 32, app_password="p" * 11)


# 거부 시 CRITICAL 로그에 원인 이름이 있어야 한다. (키, 비밀번호, 로그에 있어야 할 이름 중 하나)
REJECT_LOG_CASES = [
    pytest.param("weak-key-UNIQUE-7731", STRONG_PASSWORD, ["SECRET_KEY"], id="약한_키"),
    pytest.param(STRONG_KEY, "pw-UNIQ-99", ["APP_PASSWORD"], id="약한_비밀번호"),
    pytest.param(
        "weak-key-UNIQUE-7731", "pw-UNIQ-99", ["SECRET_KEY", "APP_PASSWORD"], id="둘다_약함"
    ),
    pytest.param("", STRONG_PASSWORD, ["SECRET_KEY"], id="키_빈값"),
    pytest.param(STRONG_KEY, "", ["APP_PASSWORD"], id="비밀번호_빈값"),
    pytest.param(" " * 40, STRONG_PASSWORD, ["SECRET_KEY"], id="키_공백"),
    pytest.param(STRONG_KEY, " " * 20, ["APP_PASSWORD"], id="비밀번호_공백"),
]


def _record_text(record: logging.LogRecord) -> str:
    return f"{record.getMessage()} {record.args!r} {record.exc_text or ''}"


@pytest.mark.parametrize(("secret_key", "app_password", "causes"), REJECT_LOG_CASES)
def test_sec1_공개_배포_거부는_CRITICAL_로그에_원인을_남기고_값은_남기지_않는다(
    caplog, secret_key, app_password, causes
):
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError):
            start_app(public_deploy=True, secret_key=secret_key, app_password=app_password)
    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical, "거부했는데 CRITICAL 기록이 없다"
    critical_text = " ".join(_record_text(r) for r in critical)
    for cause in causes:
        assert cause in critical_text, (cause, critical_text)
    logged = caplog.text + "\n".join(_record_text(r) for r in caplog.records)
    for value in (secret_key, app_password, STRONG_KEY, STRONG_PASSWORD):
        if value.strip():
            assert value not in logged


WEAK_VALUE_CASES = [
    pytest.param("weak-key-UNIQUE-7731", STRONG_PASSWORD, id="약한_키"),
    pytest.param(STRONG_KEY, "pw-UNIQ-99", id="약한_비밀번호"),
    pytest.param("weak-key-UNIQUE-7731", "pw-UNIQ-99", id="둘다_약함"),
    pytest.param("", STRONG_PASSWORD, id="키_빈값"),
    pytest.param(STRONG_KEY, "", id="비밀번호_빈값"),
    pytest.param(" " * 40, STRONG_PASSWORD, id="키_공백"),
    pytest.param(STRONG_KEY, " " * 20, id="비밀번호_공백"),
]


@pytest.mark.parametrize(("secret_key", "app_password"), WEAK_VALUE_CASES)
def test_sec1_꺼진_상태에서는_약한_값이어도_시작되고_경고가_로그에_남는다(
    caplog, secret_key, app_password
):
    with caplog.at_level(logging.WARNING):
        start_app(public_deploy=False, secret_key=secret_key, app_password=app_password)
    assert _public_deploy_warnings(caplog), "약한 값인데 app.main의 PUBLIC_DEPLOY 경고가 없다"


def _public_deploy_warnings(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == "app.main"
        and r.levelno == logging.WARNING
        and "PUBLIC_DEPLOY" in r.getMessage()
    ]


def test_sec1_꺼진_상태에서_강한_값이면_PUBLIC_DEPLOY_경고가_없다(caplog):
    with caplog.at_level(logging.DEBUG):
        start_app(public_deploy=False, secret_key=STRONG_KEY, app_password=STRONG_PASSWORD)
    assert _public_deploy_warnings(caplog) == []


@pytest.mark.parametrize(("secret_key", "app_password"), WEAK_VALUE_CASES)
def test_sec1_경고_로그에_비밀_값_자체는_남지_않는다(caplog, secret_key, app_password):
    with caplog.at_level(logging.DEBUG):
        start_app(public_deploy=False, secret_key=secret_key, app_password=app_password)
    logged = caplog.text + "\n".join(
        f"{r.getMessage()} {r.args!r} {r.exc_text or ''}" for r in caplog.records
    )
    for value in (secret_key, app_password):
        if value.strip():
            assert value not in logged


def test_sec1_기본값은_꺼진_상태라서_약한_값으로_시작된다(caplog):
    # public_deploy를 넘기지 않으면(기본) 공개 배포가 아니다. conftest 기본값(15자 키)도 시작된다.
    with caplog.at_level(logging.WARNING):
        app = create_app(make_settings())
        with TestClient(app) as client:
            assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 204
    assert _public_deploy_warnings(caplog)


def test_sec1_꺼진_상태에서_약한_값으로도_로그인할_수_있다():
    app = create_app(
        make_settings(public_deploy=False, secret_key="short-key", app_password="short-pw")
    )
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "short-pw"}).status_code == 204
        assert client.get("/api/subjects").status_code == 200


# ---------------------------------------------------------------------------
# SEC-2: 요청 본문 상한 1MiB
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prepared", LOGIN_STATES, indirect=True)
@pytest.mark.parametrize(("method", "path", "filler_key", "fields"), OVERSIZE_TARGETS)
def test_sec2_1MiB를_넘는_본문은_413_payload_too_large(prepared, method, path, filler_key, fields):
    client, subject_id = prepared
    body = json_body_of_size(MAX_BODY + 1, filler_key, **fields)
    response = client.request(
        method, path.format(sid=subject_id), content=body, headers=JSON_HEADERS
    )
    assert_payload_too_large(response)


@pytest.mark.parametrize("prepared", LOGIN_STATES, indirect=True)
@pytest.mark.parametrize(("method", "path", "filler_key", "fields"), OVERSIZE_TARGETS)
def test_sec2_Content_Length_없이_스트림으로_보내도_413(prepared, method, path, filler_key, fields):
    client, subject_id = prepared
    body = json_body_of_size(MAX_BODY + 1, filler_key, **fields)
    response = client.request(
        method,
        path.format(sid=subject_id),
        content=chunks(body),
        headers=JSON_HEADERS,
    )
    assert_payload_too_large(response)


@pytest.mark.parametrize("prepared", LOGIN_STATES, indirect=True)
@pytest.mark.parametrize(("method", "path", "filler_key", "fields"), OVERSIZE_TARGETS)
def test_sec2_상한보다_훨씬_큰_본문도_413(prepared, method, path, filler_key, fields):
    client, subject_id = prepared
    body = json_body_of_size(MAX_BODY * 4, filler_key, **fields)
    response = client.request(
        method, path.format(sid=subject_id), content=body, headers=JSON_HEADERS
    )
    assert_payload_too_large(response)


def test_sec2_미로그인에서도_401이_아니라_413이다(client):
    body = json_body_of_size(MAX_BODY + 1, "background", name="x", started_on="2026-10-01")
    response = client.post("/api/subjects", content=body, headers=JSON_HEADERS)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_sec2_413_응답에는_fields와_retry_after가_없다(auth_client):
    body = json_body_of_size(MAX_BODY + 1, "background", name="x", started_on="2026-10-01")
    error = auth_client.post("/api/subjects", content=body, headers=JSON_HEADERS).json()["error"]
    assert set(error) == {"code", "message"}


@pytest.mark.parametrize(
    ("path", "filler_key", "fields", "expected"),
    [
        pytest.param("/api/login", "password", {}, 401, id="login"),
        pytest.param(
            "/api/subjects",
            "background",
            {"name": "x", "started_on": "2026-10-01"},
            None,
            id="subjects",
        ),
    ],
)
def test_sec2_정확히_1MiB인_본문은_413이_아니다(auth_client, path, filler_key, fields, expected):
    body = json_body_of_size(MAX_BODY, filler_key, **fields)
    assert len(body) == MAX_BODY
    response = auth_client.post(path, content=body, headers=JSON_HEADERS)
    assert response.status_code != 413, response.text[:200]
    if expected is not None:
        # 로그인은 password가 1024자를 넘으므로 비교 없이 401 invalid_password다.
        assert response.status_code == expected, response.text[:200]
        assert response.json() == INVALID_PASSWORD_BODY


def test_sec2_정확히_1MiB인_본문은_핸들러까지_가서_검증_오류가_난다(auth_client):
    # background는 5000자 제한이므로 상한 이하여도 422다. 413과 구분된다.
    body = json_body_of_size(MAX_BODY, "background", name="x", started_on="2026-10-01")
    response = auth_client.post("/api/subjects", content=body, headers=JSON_HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_sec2_정확히_1MiB를_스트림으로_보내도_413이_아니다(auth_client):
    body = json_body_of_size(MAX_BODY, "background", name="x", started_on="2026-10-01")
    response = auth_client.post("/api/subjects", content=chunks(body), headers=JSON_HEADERS)
    assert response.status_code == 422


def test_sec2_거부된_POST_subjects는_주제를_만들지_않는다(auth_client):
    body = json_body_of_size(MAX_BODY + 1, "background", name="x", started_on="2026-10-01")
    assert_payload_too_large(auth_client.post("/api/subjects", content=body, headers=JSON_HEADERS))
    listing = auth_client.get("/api/subjects").json()
    assert listing["items"] == []


def test_sec2_거부된_미로그인_POST_subjects도_주제를_만들지_않는다(client):
    body = json_body_of_size(MAX_BODY + 1, "background", name="x", started_on="2026-10-01")
    assert client.post("/api/subjects", content=body, headers=JSON_HEADERS).status_code == 413
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 204
    assert client.get("/api/subjects").json()["items"] == []


def test_sec2_거부된_PATCH는_주제를_바꾸지_않는다(auth_client):
    subject_id = create_subject(auth_client, name="원래 이름")
    body = json_body_of_size(MAX_BODY + 1, "background", name="바뀐 이름")
    response = auth_client.patch(f"/api/subjects/{subject_id}", content=body, headers=JSON_HEADERS)
    assert_payload_too_large(response)
    after = auth_client.get(f"/api/subjects/{subject_id}").json()
    assert after["name"] == "원래 이름"
    assert after["background"] == ""


def test_sec2_거부된_노트_POST는_노트를_만들지_않는다(auth_client):
    subject_id = create_subject(auth_client)
    body = json_body_of_size(MAX_BODY + 1, "body", kind="remember", title="t")
    response = auth_client.post(
        f"/api/subjects/{subject_id}/notes", content=body, headers=JSON_HEADERS
    )
    assert_payload_too_large(response)
    notes = auth_client.get(f"/api/subjects/{subject_id}/notes").json()
    assert notes["total"] == 0
    assert notes["items"] == []


def test_sec2_거부된_login은_쿠키를_발급하지_않는다(client):
    body = json_body_of_size(MAX_BODY + 1, "password")
    response = client.post("/api/login", content=body, headers=JSON_HEADERS)
    assert_payload_too_large(response)
    assert response.headers.get_list("set-cookie") == []


def test_sec2_본문_50000자_한글_노트는_201로_저장된다(auth_client):
    subject_id = create_subject(auth_client)
    text = "가" * 50000
    response = auth_client.post(
        f"/api/subjects/{subject_id}/notes",
        json={"kind": "remember", "title": "가장 큰 노트", "body": text},
    )
    assert response.status_code == 201, response.text[:200]
    created = response.json()
    assert created["body"] == text
    fetched = auth_client.get(f"/api/notes/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["body"] == text


def test_sec2_본문_50000자_노트는_ASCII_이스케이프_본문도_201(auth_client):
    # 한글을 \uXXXX로 이스케이프하면 전송 크기가 약 300KB로 커지지만 상한 이하다.
    subject_id = create_subject(auth_client)
    text = "나" * 50000
    raw = json.dumps({"kind": "debug", "title": "t", "body": text}, ensure_ascii=True).encode()
    assert len(raw) < MAX_BODY
    response = auth_client.post(
        f"/api/subjects/{subject_id}/notes", content=raw, headers=JSON_HEADERS
    )
    assert response.status_code == 201, response.text[:200]


def test_sec2_상한을_넘는_PATCH_노트는_413_상한_이하는_통과(auth_client):
    subject_id = create_subject(auth_client)
    created = auth_client.post(
        f"/api/subjects/{subject_id}/notes",
        json={"kind": "remember", "title": "원래 제목"},
    ).json()
    # 노트 PATCH는 약속된 4개 외 엔드포인트지만 같은 규칙(POST·PATCH 공통)을 따른다.
    body = json_body_of_size(MAX_BODY + 1, "body", title="바뀐 제목")
    response = auth_client.patch(f"/api/notes/{created['id']}", content=body, headers=JSON_HEADERS)
    assert_payload_too_large(response)
    assert auth_client.get(f"/api/notes/{created['id']}").json()["title"] == "원래 제목"

    # 상한 이하의 PATCH는 통과해 노트가 바뀐다.
    ok = auth_client.patch(
        f"/api/notes/{created['id']}", json={"title": "바뀐 제목", "body": "새 본문"}
    )
    assert ok.status_code == 200, ok.text[:200]
    assert ok.json()["title"] == "바뀐 제목"
    after = auth_client.get(f"/api/notes/{created['id']}").json()
    assert after["title"] == "바뀐 제목"
    assert after["body"] == "새 본문"


# ---------------------------------------------------------------------------
# SEC-2: password 1024자 상한
# ---------------------------------------------------------------------------


def test_sec2_password_1024자는_평소처럼_비교되어_401(client):
    response = client.post("/api/login", json={"password": "a" * 1024})
    assert_invalid_password(response)
    assert response.headers.get_list("set-cookie") == []


def test_sec2_password_1025자도_401_invalid_password(client):
    response = client.post("/api/login", json={"password": "a" * 1025})
    assert_invalid_password(response)
    assert response.headers.get_list("set-cookie") == []


def test_sec2_password_매우_긴_값도_401이고_422나_413이_아니다(client):
    # 본문 상한(1MiB) 이하이면서 1024자를 훨씬 넘는 값.
    response = client.post("/api/login", json={"password": "a" * 100_000})
    assert_invalid_password(response)


def test_sec2_올바른_비밀번호_뒤에_글자를_붙여_1025자로_만들어도_401(client):
    padded = TEST_PASSWORD + "x" * (1025 - len(TEST_PASSWORD))
    assert len(padded) == 1025
    response = client.post("/api/login", json={"password": padded})
    assert_invalid_password(response)
    assert response.headers.get_list("set-cookie") == []
    assert client.get("/api/subjects").status_code == 401


def test_sec2_1025자_요청_5회_뒤_6번째는_429(client):
    long_password = "a" * 1025
    for attempt in range(1, 6):
        response = client.post("/api/login", json={"password": long_password})
        assert response.status_code == 401, f"{attempt}번째 시도"
    response = client.post("/api/login", json={"password": long_password})
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "too_many_attempts"
    assert error["message"] == "잠시 후 다시 시도하세요"
    assert 0 < error["retry_after"] <= 60


def test_sec2_1025자_요청_5회가_실패_횟수에_들어가_올바른_비밀번호도_잠긴다(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "a" * 1025}).status_code == 401
    response = client.post("/api/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 429
    assert response.headers.get_list("set-cookie") == []


def test_sec2_짧은_틀린_값과_긴_값의_실패가_함께_횟수에_들어간다(client):
    for password in ["wrong", "a" * 1025, "wrong", "a" * 1025, "wrong"]:
        assert client.post("/api/login", json={"password": password}).status_code == 401
    assert client.post("/api/login", json={"password": "a" * 1025}).status_code == 429


def test_sec2_password_1025자_APP_PASSWORD와_같은_값을_보내도_비교_없이_401():
    long_password = "a" * 1025
    app = create_app(make_settings(app_password=long_password))
    with TestClient(app) as client:
        response = client.post("/api/login", json={"password": long_password})
        assert_invalid_password(response)
        assert response.headers.get_list("set-cookie") == []
        assert client.get("/api/subjects").status_code == 401


def test_sec2_password_1024자_APP_PASSWORD와_같은_값은_로그인된다():
    password = "a" * 1024
    app = create_app(make_settings(app_password=password))
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": password}).status_code == 204
        assert client.get("/api/subjects").status_code == 200


# ---------------------------------------------------------------------------
# SEC-2: 순서 (413이 415보다 먼저)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prepared", LOGIN_STATES, indirect=True)
def test_sec2_1048577바이트_text_plain_본문은_415가_아니라_413(prepared):
    client, _ = prepared
    response = client.post(
        "/api/subjects",
        content=b"a" * (MAX_BODY + 1),
        headers={"Content-Type": "text/plain"},
    )
    assert_payload_too_large(response)


def test_sec2_정확히_1MiB인_text_plain_본문은_413이_아니라_415(auth_client):
    response = auth_client.post(
        "/api/subjects",
        content=b"a" * MAX_BODY,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415, response.text[:200]
    assert response.json()["error"]["code"] == "unsupported_media_type"


# ---------------------------------------------------------------------------
# SEC-2: 태그 15만 개
# ---------------------------------------------------------------------------


def _distinct_tags(count: int) -> list[str]:
    """소문자·숫자로 이뤄진 서로 다른 태그. 짧은 것부터 만들어 JSON 본문을 1MiB 아래로 맞춘다."""
    alphabet = string.ascii_lowercase + string.digits
    tags: list[str] = []
    for length in (3, 4, 5):
        for combo in itertools.product(alphabet, repeat=length):
            tags.append("".join(combo))
            if len(tags) == count:
                return tags
    raise AssertionError("태그가 모자란다")


def test_sec2_서로_다른_태그_15만_개를_담은_노트_POST는_422이고_2초_안에_끝난다(auth_client):
    subject_id = create_subject(auth_client)
    tags = _distinct_tags(150_000)
    assert len(set(tags)) == 150_000
    raw = json.dumps(
        {"kind": "remember", "title": "t", "tags": tags}, separators=(",", ":")
    ).encode()
    assert len(raw) <= MAX_BODY, "본문이 상한을 넘으면 413이라 이 시험의 의미가 없다"
    started = time.perf_counter()
    response = auth_client.post(
        f"/api/subjects/{subject_id}/notes", content=raw, headers=JSON_HEADERS
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 422, response.text[:200]
    assert response.json()["error"]["code"] == "validation_error"
    assert elapsed < 2.0, f"{elapsed:.2f}초 걸렸다"
    notes = auth_client.get(f"/api/subjects/{subject_id}/notes").json()
    assert notes["total"] == 0


# ---------------------------------------------------------------------------
# SEC-2: BodySizeLimitMiddleware 단위 시험 (가짜 receive/send)
# ---------------------------------------------------------------------------


def _scope(headers: list[tuple[bytes, bytes]], method: str = "POST") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/api/subjects",
        "raw_path": b"/api/subjects",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


class MiddlewareRun:
    def __init__(self, sent: list[dict], received_bytes: int, app_called: bool):
        self.sent = sent
        self.received_bytes = received_bytes
        self.app_called = app_called

    @property
    def starts(self) -> list[dict]:
        return [m for m in self.sent if m["type"] == "http.response.start"]

    @property
    def status(self) -> int:
        assert len(self.starts) == 1, f"http.response.start가 {len(self.starts)}번 나갔다"
        return self.starts[0]["status"]

    def body_json(self):
        body = b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")
        return json.loads(body)


def run_middleware(
    sizes: list[int],
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "POST",
) -> MiddlewareRun:
    """sizes 크기의 http.request 메시지들을 차례로 보내며 미들웨어를 직접 부른다.

    안쪽 앱은 본문을 끝까지 읽고 200을 돌려준다.
    """
    state = {"received": 0, "called": False}
    sent: list[dict] = []

    async def inner_app(scope, receive, send):
        state["called"] = True
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            state["received"] += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    messages = [
        {
            "type": "http.request",
            "body": b"a" * size,
            "more_body": index < len(sizes) - 1,
        }
        for index, size in enumerate(sizes or [0])
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    middleware = BodySizeLimitMiddleware(inner_app)
    asyncio.run(middleware(_scope(headers or [], method), receive, send))
    return MiddlewareRun(sent, state["received"], state["called"])


def test_sec2_MAX_BODY_BYTES는_1048576이다():
    assert MAX_BODY_BYTES == MAX_BODY


def test_sec2_단위_여러_메시지_합계가_정확히_1MiB면_앱이_받는다():
    sizes = [400_000, 400_000, MAX_BODY - 800_000]
    assert sum(sizes) == MAX_BODY
    result = run_middleware(sizes)
    assert result.status == 200
    assert result.received_bytes == MAX_BODY


def test_sec2_단위_정확히_1MiB이고_Content_Length도_맞으면_앱이_받는다():
    sizes = [500_000, MAX_BODY - 500_000]
    result = run_middleware(sizes, [(b"content-length", str(MAX_BODY).encode())])
    assert result.status == 200
    assert result.received_bytes == MAX_BODY


def test_sec2_단위_여러_메시지_합계가_1바이트_넘으면_413_한_번():
    sizes = [400_000, 400_000, MAX_BODY - 800_000 + 1]
    assert sum(sizes) == MAX_BODY + 1
    result = run_middleware(sizes)
    assert len(result.starts) == 1
    assert result.status == 413
    assert result.body_json() == PAYLOAD_TOO_LARGE_BODY


def test_sec2_단위_한_메시지로_1바이트_넘어도_413_한_번():
    result = run_middleware([MAX_BODY + 1])
    assert len(result.starts) == 1
    assert result.status == 413


def test_sec2_단위_Content_Length가_상한_넘게_적혀_있으면_413():
    result = run_middleware([10], [(b"content-length", str(MAX_BODY + 1).encode())])
    assert len(result.starts) == 1
    assert result.status == 413
    assert result.body_json() == PAYLOAD_TOO_LARGE_BODY


def test_sec2_단위_작게_적은_거짓_Content_Length도_실제_바이트로_거부된다():
    sizes = [600_000, 600_000]
    result = run_middleware(sizes, [(b"content-length", b"10")])
    assert len(result.starts) == 1
    assert result.status == 413
    assert result.body_json() == PAYLOAD_TOO_LARGE_BODY


def test_sec2_단위_거짓_Content_Length_작은_본문이_실제로_크면_한_메시지여도_413():
    result = run_middleware([MAX_BODY + 1], [(b"content-length", b"1")])
    assert len(result.starts) == 1
    assert result.status == 413


def test_sec2_단위_Content_Length가_서로_다른_값_두_개면_400():
    result = run_middleware([5], [(b"content-length", b"5"), (b"content-length", b"6")])
    assert len(result.starts) == 1
    assert result.status == 400
    assert "error" in result.body_json()


@pytest.mark.parametrize("value", [b"abc", b"12abc", b"1.5", b"0x10"])
def test_sec2_단위_Content_Length가_숫자가_아니면_400(value):
    result = run_middleware([5], [(b"content-length", value)])
    assert len(result.starts) == 1
    assert result.status == 400
    assert "error" in result.body_json()


@pytest.mark.parametrize("digit", [b"1", b"9"])
def test_sec2_단위_4400자리_Content_Length는_예외_없이_413(digit):
    value = digit * 4400
    assert len(value) == 4400
    result = run_middleware([5], [(b"content-length", value)])
    assert len(result.starts) == 1
    assert result.status == 413
    assert result.body_json() == PAYLOAD_TOO_LARGE_BODY


def test_sec2_단위_앞이_0으로_4400자리_채워진_Content_Length는_예외_없이_값_1로_처리된다():
    # 값은 1이므로 형식 오류(400)도 상한 초과(413)도 아니다. 자릿수가 많아도 예외가 나면 안 된다.
    value = b"0" * 4400 + b"1"
    assert len(value) == 4401
    result = run_middleware([1], [(b"content-length", value)])
    assert result.app_called
    assert result.status == 200
    assert result.received_bytes == 1


@pytest.mark.parametrize("value", [b"0", b"000", b"0" * 4400])
def test_sec2_단위_모두_0인_Content_Length는_값_0으로_처리된다(value):
    # 값은 0이므로 형식 오류(400)도 상한 초과(413)도 아니다. 앱까지 간다.
    result = run_middleware([0], [(b"content-length", value)])
    assert result.app_called
    assert result.status not in (400, 413)
    assert result.status == 200
    assert result.received_bytes == 0


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_sec2_단위_POST와_PATCH_모두_상한을_적용한다(method):
    result = run_middleware([MAX_BODY + 1], method=method)
    assert result.status == 413


# ---------------------------------------------------------------------------
# SEC-3: 공개 배포에서 쿠키 Secure
# ---------------------------------------------------------------------------

COOKIE_ATTRS_COMPARED = ("path", "httponly", "samesite", "secure")


def cookie_attrs(set_cookie: str) -> dict[str, str]:
    """Set-Cookie 한 줄에서 속성 이름 -> 값 사전(모두 소문자)을 만든다. 이름=값 항목은 뺀다."""
    attrs: dict[str, str] = {}
    for part in set_cookie.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        attrs[name.strip().lower()] = value.strip().lower()
    return attrs


def only_set_cookie(response) -> str:
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1, cookies
    assert cookies[0].startswith("session=")
    return cookies[0]


def public_app():
    return create_app(
        make_settings(public_deploy=True, secret_key=STRONG_KEY, app_password=STRONG_PASSWORD)
    )


def login_and_logout(client: TestClient, password: str) -> tuple[str, str]:
    login = client.post("/api/login", json={"password": password})
    assert login.status_code == 204, login.text
    logout = client.post("/api/logout")
    assert logout.status_code == 204, logout.text
    return only_set_cookie(login), only_set_cookie(logout)


def test_sec3_공개_배포가_켜지면_http_요청에도_로그인_Set_Cookie에_Secure가_붙는다():
    with TestClient(public_app()) as client:  # base_url은 http://testserver, 프록시 헤더 없음
        response = client.post("/api/login", json={"password": STRONG_PASSWORD})
        assert response.status_code == 204
        attrs = cookie_attrs(only_set_cookie(response))
        assert "secure" in attrs
        assert "httponly" in attrs
        assert attrs["samesite"] == "lax"
        assert attrs["max-age"] == "2592000"


def test_sec3_공개_배포가_켜지면_http_요청에도_로그아웃_Set_Cookie에_Secure가_붙는다():
    with TestClient(public_app()) as client:
        _, logout_cookie = login_and_logout(client, STRONG_PASSWORD)
        attrs = cookie_attrs(logout_cookie)
        assert "secure" in attrs
        assert attrs["max-age"] == "0"


def test_sec3_공개_배포에서_로그아웃_쿠키는_로그인_쿠키와_같은_속성을_쓴다():
    with TestClient(public_app()) as client:
        login_cookie, logout_cookie = login_and_logout(client, STRONG_PASSWORD)
    login_attrs = cookie_attrs(login_cookie)
    logout_attrs = cookie_attrs(logout_cookie)
    for name in COOKIE_ATTRS_COMPARED:
        assert logout_attrs.get(name) == login_attrs.get(name), name


def test_sec3_공개_배포에서_로그인하지_않고_로그아웃해도_Secure가_붙는다():
    with TestClient(public_app()) as client:
        response = client.post("/api/logout")
        assert response.status_code == 204
        assert "secure" in cookie_attrs(only_set_cookie(response))


def test_sec3_공개_배포에서_https_요청이어도_Secure가_붙는다():
    with TestClient(public_app(), base_url="https://testserver") as client:
        login_cookie, logout_cookie = login_and_logout(client, STRONG_PASSWORD)
    assert "secure" in cookie_attrs(login_cookie)
    assert "secure" in cookie_attrs(logout_cookie)


def test_sec3_꺼진_상태_http_로그인은_Secure_없이_되고_쿠키로_인증된다():
    app = create_app(make_settings(public_deploy=False))
    with TestClient(app) as client:
        response = client.post("/api/login", json={"password": TEST_PASSWORD})
        assert response.status_code == 204
        attrs = cookie_attrs(only_set_cookie(response))
        assert "secure" not in attrs
        assert "httponly" in attrs
        assert attrs["samesite"] == "lax"
        # 쿠키가 다음 요청에 실려 인증된다.
        assert client.get("/api/subjects").status_code == 200


def test_sec3_꺼진_상태_http_로그아웃_쿠키에도_Secure가_없다():
    app = create_app(make_settings(public_deploy=False))
    with TestClient(app) as client:
        login_cookie, logout_cookie = login_and_logout(client, TEST_PASSWORD)
    assert "secure" not in cookie_attrs(logout_cookie)
    login_attrs = cookie_attrs(login_cookie)
    logout_attrs = cookie_attrs(logout_cookie)
    for name in COOKIE_ATTRS_COMPARED:
        assert logout_attrs.get(name) == login_attrs.get(name), name


def test_sec3_꺼진_상태_https_요청이면_로그인_로그아웃_쿠키에_Secure가_붙는다():
    app = create_app(make_settings(public_deploy=False))
    with TestClient(app, base_url="https://testserver") as client:
        login_cookie, logout_cookie = login_and_logout(client, TEST_PASSWORD)
    assert "secure" in cookie_attrs(login_cookie)
    assert "secure" in cookie_attrs(logout_cookie)


# ---------------------------------------------------------------------------
# SEC-4: X-Forwarded-For를 바꿔도 같은 잠금 카운터
# ---------------------------------------------------------------------------


def login_from(client: TestClient, password: str, forwarded_for: str | None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for is not None else {}
    return client.post("/api/login", json={"password": password}, headers=headers)


def test_sec4_요청마다_다른_X_Forwarded_For로_5번_틀리면_6번째는_429(client):
    for attempt in range(1, 6):
        response = login_from(client, "wrong-password", f"203.0.113.{attempt}")
        assert response.status_code == 401, f"{attempt}번째 시도"
    response = login_from(client, "wrong-password", "203.0.113.200")
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "too_many_attempts"
    assert error["message"] == "잠시 후 다시 시도하세요"
    assert 0 < error["retry_after"] <= 60


def test_sec4_다양한_모양의_X_Forwarded_For_값도_같은_카운터를_쓴다(client):
    values = ["198.51.100.7", "198.51.100.7, 203.0.113.3", "2001:db8::1", "unknown", "1.1.1.1"]
    for attempt, value in enumerate(values, start=1):
        assert login_from(client, "wrong-password", value).status_code == 401, f"{attempt}번째"
    assert login_from(client, "wrong-password", "9.9.9.9").status_code == 429


def test_sec4_올바른_비밀번호에_헤더를_바꿔_붙여도_잠금이_풀리지_않는다(client):
    for attempt in range(1, 6):
        assert login_from(client, "wrong-password", f"203.0.113.{attempt}").status_code == 401, (
            f"{attempt}번째 시도"
        )
    for value in ["203.0.113.50", "203.0.113.51", "198.51.100.9, 10.0.0.1", None]:
        response = login_from(client, TEST_PASSWORD, value)
        assert response.status_code == 429, value
        assert response.headers.get_list("set-cookie") == []
    assert client.get("/api/subjects").status_code == 401


def test_sec4_헤더가_있는_요청과_없는_요청의_실패가_한_카운터에_합쳐진다(client):
    assert login_from(client, "wrong-password", None).status_code == 401
    assert login_from(client, "wrong-password", "203.0.113.1").status_code == 401
    assert login_from(client, "wrong-password", None).status_code == 401
    assert login_from(client, "wrong-password", "203.0.113.2").status_code == 401
    assert login_from(client, "wrong-password", "203.0.113.3").status_code == 401
    assert login_from(client, "wrong-password", None).status_code == 429
    assert login_from(client, "wrong-password", "203.0.113.4").status_code == 429


# ---------------------------------------------------------------------------
# SEC-5 / SEC-6 공용 도우미
# ---------------------------------------------------------------------------

NOT_FOUND_CODE = "not_found"
FORBIDDEN_BODY = {
    "error": {"code": "forbidden", "message": "다른 사이트에서 보낸 요청입니다"},
}
INTERNAL_ERROR_BODY = {
    "error": {"code": "internal_error", "message": "서버 오류가 발생했습니다"},
}
UNAUTHORIZED_BODY = {
    "error": {"code": "unauthorized", "message": "로그인이 필요합니다"},
}
Q_BAD_CHAR_MESSAGE = "검색어에 쓸 수 없는 문자가 있습니다"
# SEC-5: 제어 문자나 쉼표로 거부되면 길이 문구 대신 그 이유를 말하는 문구를 쓴다.
ONE_LINE_CONTROL_MESSAGE = "줄바꿈이나 제어 문자를 쓸 수 없습니다"
MULTILINE_CONTROL_MESSAGE = "쓸 수 없는 제어 문자가 있습니다"
TAG_CONTROL_MESSAGE = "태그에 쉼표나 제어 문자를 쓸 수 없습니다"
NAME_LENGTH_MESSAGE = "이름은 1~100자여야 합니다"
TITLE_LENGTH_MESSAGE = "제목은 1~200자여야 합니다"
TAGS_LENGTH_MESSAGE = "태그는 최대 20개, 각 1~30자"
TAG_QUERY_CONTROL_MESSAGE = "태그 조건에 쓸 수 없는 문자가 있습니다"
TAG_QUERY_LENGTH_MESSAGE = "태그 조건은 최대 20개, 각 1~30자입니다"


def assert_error_shape(response, status: int) -> dict:
    """공통 오류 모양 {"error": {"code", "message", ...}} 이고 FastAPI 기본 detail이 아니다."""
    assert response.status_code == status, response.text[:200]
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


def assert_validation_fields(response, *names: str) -> dict:
    error = assert_error_shape(response, 422)
    assert error["code"] == "validation_error"
    for name in names:
        assert name in error["fields"], error
        assert isinstance(error["fields"][name], str) and error["fields"][name]
    return error


def call_asgi_response(
    app, path: str, query: bytes, headers=(), body: bytes = b"", method: str = "POST"
) -> tuple[int, bytes]:
    """ASGI 앱을 직접 부른다. 앱이 예외를 밖으로 던지면 그대로 테스트가 실패한다."""
    sent: list[dict] = []
    messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "root_path": "",
        "headers": list(headers),
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1, sent
    body_bytes = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return starts[0]["status"], body_bytes


def call_asgi(app, path: str, query: bytes, headers=(), body: bytes = b"", method: str = "POST"):
    return call_asgi_response(app, path, query, headers, body, method)[0]


# ---------------------------------------------------------------------------
# SEC-5: 화면 주소 (잘못된 id)
# ---------------------------------------------------------------------------

BAD_PAGE_PATHS = [
    "/subjects/abc",
    "/subjects/abc/notes/new",
    "/notes/abc",
    "/notes/abc/edit",
    "/subjects/0",
    "/notes/-1",
]


@pytest.mark.parametrize("path", BAD_PAGE_PATHS)
def test_sec5_미로그인에서_잘못된_id_화면_주소는_302_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302, response.text[:200]
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("path", BAD_PAGE_PATHS)
def test_sec5_로그인_상태에서_잘못된_id_화면_주소는_404_S6_HTML(auth_client, path):
    """F11: 화면 주소의 404는 JSON이 아니라 같은 상태 코드의 S6 HTML이다."""
    response = auth_client.get(path, follow_redirects=False)
    assert response.status_code == 404, response.text[:200]
    assert response.headers["content-type"].startswith("text/html")
    assert "페이지를 찾을 수 없습니다" in response.text


# ---------------------------------------------------------------------------
# SEC-5: 잘못된 UTF-8 쿼리
# ---------------------------------------------------------------------------


def test_sec5_미로그인_logout_잘못된_UTF8_쿼리는_204(client):
    response = client.post("/api/logout?x=%FF")
    assert response.status_code == 204, response.text[:200]


def test_sec5_로그인_logout_잘못된_UTF8_쿼리는_204(auth_client):
    response = auth_client.post("/api/logout?x=%FF")
    assert response.status_code == 204, response.text[:200]


def test_sec5_login_잘못된_UTF8_쿼리는_맞는_비밀번호면_204_틀리면_401(client):
    wrong = client.post("/api/login?x=%FF", json={"password": "wrong"})
    assert_invalid_password(wrong)
    response = client.post("/api/login?x=%FF", json={"password": TEST_PASSWORD})
    assert response.status_code == 204, response.text[:200]


def test_sec5_로그인_상태에서_login_잘못된_UTF8_쿼리는_204(auth_client):
    response = auth_client.post("/api/login?x=%FF", json={"password": TEST_PASSWORD})
    assert response.status_code == 204, response.text[:200]


def test_sec5_원시_바이트_쿼리도_앱이_예외_없이_응답한다(client):
    # httpx는 %FF를 ASCII로 보내므로, 진짜 0xFF 바이트는 ASGI scope로 직접 만든다.
    app = client.app
    raw = b"x=\xff"
    login_body = json.dumps({"password": TEST_PASSWORD}).encode()
    json_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(login_body)).encode()),
    ]

    assert call_asgi(app, "/api/logout", raw) < 500
    assert call_asgi(app, "/api/login", raw, json_headers, login_body) < 500
    assert call_asgi(app, "/api/subjects", raw, method="GET") < 500
    assert call_asgi(app, "/", raw, method="GET") < 500
    assert call_asgi(app, "/login", raw, method="GET") < 500


def test_sec5_로그인_상태의_원시_바이트_쿼리도_앱이_예외_없이_응답한다(auth_client):
    app = auth_client.app
    cookie = auth_client.cookies.get("session")
    assert cookie
    headers = [(b"cookie", f"session={cookie}".encode())]
    raw = b"x=\xff"

    assert call_asgi(app, "/api/logout", raw, headers) < 500
    assert call_asgi(app, "/api/subjects", raw, headers, method="GET") < 500
    assert call_asgi(app, "/", raw, headers, method="GET") < 500


def assert_common_error_response(status: int, body: bytes):
    assert status >= 400, status
    parsed = json.loads(body)
    assert set(parsed) == {"error"}, parsed
    assert isinstance(parsed["error"]["code"], str) and parsed["error"]["code"]
    assert isinstance(parsed["error"]["message"], str) and parsed["error"]["message"]


def test_sec5_끝_슬래시_경로의_원시_바이트_쿼리도_예외_없이_공통_오류_모양(client):
    # /api/subjects/ 는 끝 슬래시 때문에 라우터 리다이렉트나 404를 거친다. 그래도 예외는 없다.
    status, body = call_asgi_response(client.app, "/api/subjects/", b"x=\xff", method="GET")
    assert status < 500
    assert_common_error_response(status, body)


def test_sec5_로그인_상태의_끝_슬래시_경로_원시_바이트_쿼리도_예외_없이_공통_오류_모양(auth_client):
    cookie = auth_client.cookies.get("session")
    assert cookie
    headers = [(b"cookie", f"session={cookie}".encode())]
    status, body = call_asgi_response(
        auth_client.app, "/api/subjects/", b"x=\xff", headers, method="GET"
    )
    assert status < 500
    assert_common_error_response(status, body)


# ---------------------------------------------------------------------------
# SEC-5: 제어 문자 422
# ---------------------------------------------------------------------------


@pytest.fixture
def world(auth_client):
    """주제·공부 기록·노트를 하나씩 만들어 둔다. PATCH 시험의 대상이다."""
    subject = auth_client.post(
        "/api/subjects", json={"name": "원본", "started_on": "2026-10-01"}
    ).json()
    session = auth_client.post(
        f"/api/subjects/{subject['id']}/sessions",
        json={"studied_on": "2026-10-01", "minutes": 30},
    ).json()
    note = auth_client.post(
        f"/api/subjects/{subject['id']}/notes", json={"kind": "remember", "title": "원본 제목"}
    ).json()
    return {
        "client": auth_client,
        "subject": subject["id"],
        "session": session["id"],
        "note": note["id"],
    }


# 리소스별 (생성 주소, 수정 주소, 생성에 필요한 기본 필드)
RESOURCES = {
    "subject": ("/api/subjects", "/api/subjects/{id}", {"name": "n", "started_on": "2026-10-01"}),
    "session": (
        "/api/subjects/{subject}/sessions",
        "/api/sessions/{id}",
        {"studied_on": "2026-10-01", "minutes": 30},
    ),
    "note": (
        "/api/subjects/{subject}/notes",
        "/api/notes/{id}",
        {"kind": "remember", "title": "t"},
    ),
}


def send_fields(world, resource: str, method: str, fields: dict):
    """method가 POST면 기본 필드에 fields를 덮어 만들고, PATCH면 fields만 보낸다."""
    create_path, patch_path, base = RESOURCES[resource]
    client = world["client"]
    if method == "POST":
        path = create_path.format(subject=world["subject"])
        return client.post(path, json={**base, **fields})
    path = patch_path.format(id=world[resource])
    return client.patch(path, json=fields)


# (리소스, 필드): 한 줄 필드
ONE_LINE_FIELDS = [("subject", "name"), ("session", "memo"), ("note", "title")]
ONE_LINE_BAD_VALUES = [
    pytest.param("a\x00b", id="NUL_중간"),
    pytest.param("a\nb", id="줄바꿈"),
    pytest.param("\u0000", id="NUL만"),
    pytest.param("a\x00", id="NUL_끝"),
    pytest.param("a\tb", id="탭"),
    pytest.param("a\x01", id="SOH"),
    pytest.param("a\r", id="CR"),
]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("value", ONE_LINE_BAD_VALUES)
@pytest.mark.parametrize(("resource", "field"), ONE_LINE_FIELDS)
def test_sec5_한_줄_필드의_제어_문자는_422(world, resource, field, value, method):
    response = send_fields(world, resource, method, {field: value})
    assert_validation_fields(response, field)


# (리소스, 필드, 값): 제어 문자 문구를 확인할 한 줄 필드
ONE_LINE_MESSAGE_CASES = [
    pytest.param("subject", "name", "a\nb", id="이름_줄바꿈"),
    pytest.param("note", "title", "a\tb", id="제목_탭"),
    pytest.param("session", "memo", "a\x01", id="메모_SOH"),
]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(("resource", "field", "value"), ONE_LINE_MESSAGE_CASES)
def test_sec5_한_줄_필드의_제어_문자_422는_이유_문구(world, resource, field, value, method):
    response = send_fields(world, resource, method, {field: value})
    error = assert_validation_fields(response, field)
    assert error["fields"][field] == ONE_LINE_CONTROL_MESSAGE


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    ("resource", "field", "empty_message"),
    [
        pytest.param("subject", "name", NAME_LENGTH_MESSAGE, id="이름"),
        pytest.param("note", "title", TITLE_LENGTH_MESSAGE, id="제목"),
    ],
)
def test_sec5_빈_값은_계속_길이_문구로_422(world, resource, field, empty_message, method):
    response = send_fields(world, resource, method, {field: ""})
    error = assert_validation_fields(response, field)
    assert error["fields"][field] == empty_message


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_sec5_31자_태그는_계속_개수와_길이_문구로_422(world, method):
    response = send_fields(world, "note", method, {"tags": ["a" * 31]})
    error = assert_validation_fields(response, "tags")
    assert error["fields"]["tags"] == TAGS_LENGTH_MESSAGE


def test_sec5_제어_문자_422는_주제를_만들지도_바꾸지도_않는다(world):
    client = world["client"]
    send_fields(world, "subject", "POST", {"name": "a\x00b"})
    send_fields(world, "subject", "PATCH", {"name": "a\nb"})
    items = client.get("/api/subjects").json()["items"]
    assert [item["name"] for item in items] == ["원본"]


def test_sec5_제어_문자_422는_노트를_만들지도_바꾸지도_않는다(world):
    client = world["client"]
    send_fields(world, "note", "POST", {"title": "a\x00"})
    send_fields(world, "note", "PATCH", {"title": "a\tb"})
    listing = client.get(f"/api/subjects/{world['subject']}/notes").json()
    assert [n["title"] for n in listing["items"]] == ["원본 제목"]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "tag",
    [
        pytest.param("a\x00", id="NUL"),
        pytest.param("a,b", id="쉼표"),
        pytest.param("a\x01b", id="SOH"),
        pytest.param("a\nb", id="줄바꿈_중간"),
        pytest.param("a\tb", id="탭_중간"),
    ],
)
def test_sec5_태그의_제어_문자와_쉼표는_422(world, tag, method):
    response = send_fields(world, "note", method, {"tags": ["ok", tag]})
    error = assert_validation_fields(response, "tags")
    assert error["fields"]["tags"] == TAG_CONTROL_MESSAGE


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_sec5_정상_태그는_그대로_저장된다(world, method):
    response = send_fields(world, "note", method, {"tags": ["pandas", "csv-2", "한글"]})
    assert response.status_code in (200, 201), response.text[:200]
    assert response.json()["tags"] == ["pandas", "csv-2", "한글"]


MULTILINE_FIELDS = [("subject", "background"), ("note", "body")]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "value", [pytest.param("a\x00", id="NUL"), pytest.param("a\x07", id="BEL")]
)
@pytest.mark.parametrize(("resource", "field"), MULTILINE_FIELDS)
def test_sec5_여러_줄_필드의_NUL과_제어_문자는_422(world, resource, field, value, method):
    response = send_fields(world, resource, method, {field: value})
    assert_validation_fields(response, field)


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(("resource", "field"), MULTILINE_FIELDS)
def test_sec5_여러_줄_필드의_NUL_422는_이유를_말하는_문구(world, resource, field, method):
    response = send_fields(world, resource, method, {field: "a\x00"})
    error = assert_validation_fields(response, field)
    assert error["fields"][field] == MULTILINE_CONTROL_MESSAGE


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("첫째\n둘째", id="LF"),
        pytest.param("첫째\r\n둘째", id="CRLF"),
        pytest.param("첫째\t둘째", id="탭"),
        pytest.param("# 제목\n\n```python\n\tprint(1)\r\n```\n", id="코드블록"),
    ],
)
@pytest.mark.parametrize(("resource", "field"), MULTILINE_FIELDS)
def test_sec5_여러_줄_필드의_줄바꿈과_탭은_그대로_저장된다(world, resource, field, value, method):
    response = send_fields(world, resource, method, {field: value})
    assert response.status_code in (200, 201), response.text[:200]
    assert response.json()[field] == value
    path = {"subject": "/api/subjects/{id}", "note": "/api/notes/{id}"}[resource]
    fetched = world["client"].get(path.format(id=response.json()["id"])).json()
    assert fetched[field] == value


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("tag=a%00b", id="NUL_중간"),
        pytest.param("tag=a%00", id="NUL_끝"),
        pytest.param("tag=%01", id="SOH"),
        pytest.param("tag=a%0Ab", id="줄바꿈"),
        pytest.param("tag=a%09b", id="탭"),
        pytest.param("tag=a%2Cb", id="쉼표"),
        pytest.param("tag=ok&tag=a%00b", id="둘째_tag에_NUL"),
    ],
)
def test_sec5_쿼리_tag의_제어_문자와_쉼표는_422_fields_tag_이유_문구(world, query):
    client = world["client"]
    response = client.get(f"/api/subjects/{world['subject']}/notes?{query}")
    error = assert_validation_fields(response, "tag")
    assert error["fields"]["tag"] == TAG_QUERY_CONTROL_MESSAGE


def test_sec5_쿼리_tag_21개는_길이_문구로_422(world):
    client = world["client"]
    query = "&".join(f"tag=t{i}" for i in range(21))
    response = client.get(f"/api/subjects/{world['subject']}/notes?{query}")
    error = assert_validation_fields(response, "tag")
    assert error["fields"]["tag"] == TAG_QUERY_LENGTH_MESSAGE


def test_sec5_쿼리_tag_31자는_길이_문구로_422(world):
    client = world["client"]
    response = client.get(f"/api/subjects/{world['subject']}/notes?tag={'a' * 31}")
    error = assert_validation_fields(response, "tag")
    assert error["fields"]["tag"] == TAG_QUERY_LENGTH_MESSAGE


def test_sec5_쿼리_tag_20개_30자는_통과한다(world):
    client = world["client"]
    query = "&".join(f"tag={chr(97 + i) * 30}" for i in range(20))
    response = client.get(f"/api/subjects/{world['subject']}/notes?{query}")
    assert response.status_code == 200, response.text[:200]


def test_sec5_쿼리_q에_NUL이_있으면_422_fields_q_문구(world):
    client = world["client"]
    response = client.get(f"/api/subjects/{world['subject']}/notes?q=a%00")
    error = assert_validation_fields(response, "q")
    assert error["fields"]["q"] == Q_BAD_CHAR_MESSAGE


def test_sec5_쿼리_tag와_q가_정상이면_200(world):
    client = world["client"]
    response = client.get(f"/api/subjects/{world['subject']}/notes?tag=pandas&q=%ED%95%9C")
    assert response.status_code == 200, response.text[:200]


# ---------------------------------------------------------------------------
# SEC-5: 날짜 422 / 경계 날짜 저장
# ---------------------------------------------------------------------------

DATE_FIELDS = [
    ("subject", "started_on"),
    ("subject", "target_date"),
    ("session", "studied_on"),
]
BAD_DATES = [
    pytest.param("0000-01-01", id="0000년"),
    pytest.param("٢٠٢٦-١٠-٣١", id="아랍_숫자"),
    pytest.param("2026-02-30", id="없는_날짜"),
]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("value", BAD_DATES)
@pytest.mark.parametrize(("resource", "field"), DATE_FIELDS)
def test_sec5_잘못된_날짜는_422(world, resource, field, value, method):
    response = send_fields(world, resource, method, {field: value})
    assert_validation_fields(response, field)


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31"])
@pytest.mark.parametrize(("resource", "field"), DATE_FIELDS)
def test_sec5_경계_날짜는_저장된다(world, resource, field, value, method):
    fields = {field: value}
    if (resource, field, value) == ("subject", "target_date", "0001-01-01"):
        # F12: 목표일은 시작일보다 빠를 수 없으므로 시작일도 같은 날로 맞춘다(같은 날은 허용).
        fields["started_on"] = value
    response = send_fields(world, resource, method, fields)
    assert response.status_code in (200, 201), response.text[:200]
    assert response.json()[field] == value
    if resource == "subject":
        fetched = world["client"].get(f"/api/subjects/{response.json()['id']}").json()
        assert fetched[field] == value
    else:
        listing = world["client"].get(f"/api/subjects/{world['subject']}/sessions").json()
        assert value in [item[field] for item in listing["items"]]


# ---------------------------------------------------------------------------
# SEC-5: 로그아웃 Sec-Fetch-Site
# ---------------------------------------------------------------------------


def test_sec5_cross_site_로그아웃은_403이고_쿠키를_지우지_않는다(auth_client):
    response = auth_client.post("/api/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403, response.text[:200]
    assert response.json() == FORBIDDEN_BODY
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers.get_list("set-cookie") == []


def test_sec5_cross_site_로그아웃_뒤에도_세션이_유지된다(auth_client):
    auth_client.post("/api/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert auth_client.get("/api/subjects").status_code == 200


def test_sec5_미로그인_cross_site_로그아웃도_403(client):
    response = client.post("/api/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_BODY
    assert response.headers.get_list("set-cookie") == []


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_sec5_허용된_Sec_Fetch_Site_값의_로그아웃은_204(auth_client, site):
    response = auth_client.post("/api/logout", headers={"Sec-Fetch-Site": site})
    assert response.status_code == 204, response.text[:200]
    assert response.headers.get_list("set-cookie"), "쿠키를 지우는 Set-Cookie가 있어야 한다"
    assert auth_client.get("/api/subjects").status_code == 401


def test_sec5_Sec_Fetch_Site_헤더가_없는_로그아웃은_204(auth_client):
    response = auth_client.post("/api/logout")
    assert response.status_code == 204
    assert auth_client.get("/api/subjects").status_code == 401


# ---------------------------------------------------------------------------
# SEC-5: LoginRateLimiter 단위 (IPv6 /64, 추적 상한)
# ---------------------------------------------------------------------------


def burn(limiter: LoginRateLimiter, ip: str, times: int) -> list:
    return [limiter.acquire(ip) for _ in range(times)]


def is_locked(result) -> bool:
    return isinstance(result, int) and not isinstance(result, bool) and result > 0


V6_A = "2001:db8:1:2::1"
V6_A_SAME_64 = "2001:db8:1:2:ffff:ffff:ffff:ffff"
V6_OTHER_64 = "2001:db8:1:3::1"


def test_sec5_단위_같은_64의_IPv6_두_주소는_카운터를_공유한다():
    limiter = LoginRateLimiter()
    assert not any(is_locked(r) for r in burn(limiter, V6_A, 3))
    assert not any(is_locked(r) for r in burn(limiter, V6_A_SAME_64, 2))
    assert is_locked(limiter.acquire(V6_A))
    assert is_locked(limiter.acquire(V6_A_SAME_64))


def test_sec5_단위_다른_64의_IPv6는_카운터가_나뉜다():
    limiter = LoginRateLimiter()
    assert not any(is_locked(r) for r in burn(limiter, V6_A, 5))
    assert is_locked(limiter.acquire(V6_A))
    # 다른 /64는 영향을 받지 않고 자기 몫의 5회를 쓸 수 있다.
    assert not any(is_locked(r) for r in burn(limiter, V6_OTHER_64, 5))
    assert is_locked(limiter.acquire(V6_OTHER_64))


def test_sec5_단위_IPv4_두_주소는_카운터가_나뉜다():
    limiter = LoginRateLimiter()
    assert not any(is_locked(r) for r in burn(limiter, "203.0.113.1", 5))
    assert is_locked(limiter.acquire("203.0.113.1"))
    assert not any(is_locked(r) for r in burn(limiter, "203.0.113.2", 5))
    assert is_locked(limiter.acquire("203.0.113.2"))


def test_sec5_단위_같은_24의_IPv4도_묶이지_않는다():
    limiter = LoginRateLimiter()
    burn(limiter, "198.51.100.10", 6)
    assert not is_locked(limiter.acquire("198.51.100.11"))


def test_sec5_단위_reset은_같은_64의_다른_주소_잠금도_푼다():
    limiter = LoginRateLimiter()
    burn(limiter, V6_A, 5)
    assert is_locked(limiter.acquire(V6_A))
    limiter.reset(V6_A_SAME_64)
    assert not is_locked(limiter.acquire(V6_A))


def test_sec5_단위_reset은_다른_64를_건드리지_않는다():
    limiter = LoginRateLimiter()
    burn(limiter, V6_A, 5)
    limiter.reset(V6_OTHER_64)
    assert is_locked(limiter.acquire(V6_A))


def test_sec5_단위_reset_뒤에는_다시_5회를_쓸_수_있다():
    limiter = LoginRateLimiter()
    burn(limiter, "203.0.113.9", 5)
    assert is_locked(limiter.acquire("203.0.113.9"))
    limiter.reset("203.0.113.9")
    assert not any(is_locked(r) for r in burn(limiter, "203.0.113.9", 5))


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "unknown",
        "not-an-ip",
        "999.1.1.1",
        "2001:db8::zz",
        "1.2.3.4, 5.6.7.8",
        "\x00",
        "한글",
        "a" * 5000,
    ],
)
def test_sec5_단위_파싱할_수_없는_값에도_예외가_없다(value):
    limiter = LoginRateLimiter()
    for _ in range(7):
        limiter.acquire(value)
    limiter.reset(value)
    limiter.acquire(value)


def distinct_ips(start: int, count: int):
    base = int(ipaddress.IPv4Address("11.0.0.0")) + start
    return (str(ipaddress.IPv4Address(base + i)) for i in range(count))


SMALL_LIMIT = 10


def tracked_count(limiter: LoginRateLimiter) -> int:
    """추적 중인 항목 수. 내부 이름에 기대지 않고 limiter가 가진 사전의 크기를 모두 더한다."""
    return sum(len(value) for value in vars(limiter).values() if isinstance(value, dict))


def test_sec5_단위_추적_상한을_넘겨도_진행_중인_최근_IP의_실패_횟수가_남는다():
    limiter = LoginRateLimiter(max_tracked=SMALL_LIMIT)
    target = "203.0.113.77"
    offset = 0
    # 대상 IP가 5번 시도하는 사이사이에 상한보다 적은 서로 다른 IP를 흘려 보낸다.
    # 합계는 상한(10)을 훨씬 넘지만 대상은 그때마다 가장 최근 항목이다.
    results = []
    for _ in range(5):
        results.append(limiter.acquire(target))
        for ip in distinct_ips(offset, 6):
            limiter.acquire(ip)
        offset += 6
    assert offset > SMALL_LIMIT * 2
    assert not any(is_locked(r) for r in results)
    # 6번째는 잠겨야 한다. 상한 때문에 실패 횟수가 지워졌다면 잠기지 않는다.
    assert is_locked(limiter.acquire(target))


def test_sec5_단위_추적_상한을_넘겨도_이미_걸린_잠금이_사라지지_않는다():
    limiter = LoginRateLimiter(max_tracked=SMALL_LIMIT)
    target = "203.0.113.78"
    burn(limiter, target, 5)
    assert is_locked(limiter.acquire(target))
    for ip in distinct_ips(0, SMALL_LIMIT * 5):
        limiter.acquire(ip)
    assert is_locked(limiter.acquire(target))


def test_sec5_단위_추적_상한을_넘겨도_새_IP는_계속_받아_준다():
    limiter = LoginRateLimiter(max_tracked=SMALL_LIMIT)
    for ip in distinct_ips(0, SMALL_LIMIT * 5):
        assert not is_locked(limiter.acquire(ip))
    assert not is_locked(limiter.acquire("203.0.113.200"))


def test_sec5_단위_추적_개수는_상한을_넘지_않는다():
    limiter = LoginRateLimiter(max_tracked=SMALL_LIMIT)
    for ip in distinct_ips(0, SMALL_LIMIT * 5):
        limiter.acquire(ip)
        assert tracked_count(limiter) <= SMALL_LIMIT


def test_sec5_단위_전부_잠긴_상태에서_새_키가_와도_예외가_없고_추적_개수가_상한을_넘지_않는다():
    limiter = LoginRateLimiter(max_tracked=SMALL_LIMIT)
    locked_ips = list(distinct_ips(0, SMALL_LIMIT))
    for ip in locked_ips:
        burn(limiter, ip, 5)
    assert tracked_count(limiter) <= SMALL_LIMIT
    for ip in distinct_ips(1000, SMALL_LIMIT * 3):
        result = limiter.acquire(ip)  # 예외가 나면 안 된다.
        assert not is_locked(result)
        assert tracked_count(limiter) <= SMALL_LIMIT


def test_sec5_단위_상한이_1이어도_예외가_없고_추적_개수가_1을_넘지_않는다():
    limiter = LoginRateLimiter(max_tracked=1)
    burn(limiter, "203.0.113.1", 5)
    for ip in distinct_ips(0, 5):
        limiter.acquire(ip)
        assert tracked_count(limiter) <= 1


def test_sec5_단위_IPv4_mapped_IPv6는_주소마다_다른_키다():
    first = rate_limit_key("::ffff:192.0.2.1")
    second = rate_limit_key("::ffff:192.0.2.2")
    assert first != second


def test_sec5_단위_IPv4_mapped_IPv6_두_주소는_카운터가_나뉜다():
    limiter = LoginRateLimiter()
    assert not any(is_locked(r) for r in burn(limiter, "::ffff:192.0.2.1", 5))
    assert is_locked(limiter.acquire("::ffff:192.0.2.1"))
    assert not any(is_locked(r) for r in burn(limiter, "::ffff:192.0.2.2", 5))
    assert is_locked(limiter.acquire("::ffff:192.0.2.2"))


# ---------------------------------------------------------------------------
# SEC-6: 보안 헤더
# ---------------------------------------------------------------------------


def assert_security_headers(response):
    headers = response.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"
    csp = headers.get("content-security-policy")
    assert csp, "Content-Security-Policy가 없다"
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "unsafe-inline" not in csp


def oversize_post(client):
    body = json_body_of_size(MAX_BODY + 1, "background", name="x", started_on="2026-10-01")
    return client.post("/api/subjects", content=body, headers=JSON_HEADERS)


def test_sec6_로그인_화면_HTML에_보안_헤더가_있다(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert_security_headers(response)


def test_sec6_정적_파일에_보안_헤더가_있다(client):
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert_security_headers(response)


def test_sec6_401_API_응답에_보안_헤더가_있다(client):
    response = client.get("/api/subjects")
    assert response.status_code == 401
    assert_security_headers(response)


def test_sec6_404_응답에_보안_헤더가_있다(auth_client):
    api_missing = auth_client.get("/api/subjects/99999")
    assert api_missing.status_code == 404
    assert_security_headers(api_missing)
    page_missing = auth_client.get("/no-such-page")
    assert page_missing.status_code == 404
    assert_security_headers(page_missing)


def test_sec6_미로그인_404_응답에도_보안_헤더가_있다(client):
    response = client.get("/no-such-page", follow_redirects=False)
    assert response.status_code == 404
    assert_security_headers(response)


@pytest.mark.parametrize("state", LOGIN_STATES)
def test_sec6_413_응답에_보안_헤더가_있다(request, state):
    client = request.getfixturevalue("auth_client" if state == "auth" else "client")
    response = oversize_post(client)
    assert response.status_code == 413
    assert_security_headers(response)


def test_sec6_422_405_응답에도_보안_헤더가_있다(auth_client):
    invalid = auth_client.post("/api/subjects", json={"name": "", "started_on": "2026-10-01"})
    assert invalid.status_code == 422
    assert_security_headers(invalid)
    not_allowed = auth_client.delete("/api/subjects")
    assert not_allowed.status_code == 405
    assert_security_headers(not_allowed)


def test_sec6_정상_API_응답과_로그인한_HTML에도_보안_헤더가_있다(auth_client):
    assert_security_headers(auth_client.get("/api/subjects"))
    assert_security_headers(auth_client.get("/", follow_redirects=False))


def test_sec6_CSP는_인라인_허용_없이_self만_스크립트로_허용한다(client):
    csp = client.get("/login").headers["content-security-policy"]
    directives = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    assert directives["script-src"] == ["'self'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["object-src"] == ["'none'"]
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp


# ---------------------------------------------------------------------------
# SEC-6: Cache-Control, HSTS
# ---------------------------------------------------------------------------


def test_sec6_API_200_응답은_no_store(auth_client):
    response = auth_client.get("/api/subjects")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_sec6_API_401_응답은_no_store(client):
    response = client.get("/api/subjects")
    assert response.status_code == 401
    assert response.headers.get("cache-control") == "no-store"


def test_sec6_API_404_응답은_no_store(auth_client):
    response = auth_client.get("/api/subjects/99999")
    assert response.status_code == 404
    assert response.headers.get("cache-control") == "no-store"


def test_sec6_API_내보내기_응답은_no_store(auth_client):
    sid = create_subject(auth_client)
    response = auth_client.get(f"/api/subjects/{sid}/export")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_sec6_API_POST_422_응답과_로그인_응답도_no_store(auth_client, client):
    invalid = auth_client.post("/api/subjects", json={"name": "", "started_on": "2026-10-01"})
    assert invalid.status_code == 422
    assert invalid.headers.get("cache-control") == "no-store"
    login = client.post("/api/login", json={"password": TEST_PASSWORD})
    assert login.status_code == 204
    assert login.headers.get("cache-control") == "no-store"


def test_sec6_HTML_응답에는_no_store가_없다(client):
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "cache-control" not in login_page.headers
    client.post("/api/login", json={"password": TEST_PASSWORD})
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 200
    assert "cache-control" not in home.headers


def test_sec6_공개_배포를_켜면_HSTS_헤더가_있다():
    with TestClient(public_app()) as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert response.headers.get("strict-transport-security")
        api = client.get("/api/subjects")
        assert api.headers.get("strict-transport-security")


def test_sec6_공개_배포를_끄면_HSTS_헤더가_없다(client):
    assert "strict-transport-security" not in client.get("/login").headers
    assert "strict-transport-security" not in client.get("/api/subjects").headers


# ---------------------------------------------------------------------------
# SEC-6: 화면 템플릿에 인라인 스크립트·이벤트 속성·style 속성이 없다
# ---------------------------------------------------------------------------

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
EVENT_ATTR_RE = re.compile(r"<[a-zA-Z][^>]*?\son[a-zA-Z]+\s*=", re.DOTALL)
STYLE_ATTR_RE = re.compile(r"<[a-zA-Z][^>]*?\sstyle\s*=", re.DOTALL)


def assert_no_inline_code(path: str, html: str):
    for attrs, body in SCRIPT_RE.findall(html):
        assert body.strip() == "", f"{path}: 인라인 <script> 본문이 있다: {body.strip()[:80]!r}"
        assert re.search(r"\bsrc\s*=", attrs, re.IGNORECASE), f"{path}: src 없는 <script>"
    assert not EVENT_ATTR_RE.search(html), f"{path}: onclick 같은 이벤트 속성이 있다"
    assert not STYLE_ATTR_RE.search(html), f"{path}: style 속성이 있다"


def test_sec6_로그인_화면에_인라인_코드가_없다(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert_no_inline_code("/login", response.text)


def test_sec6_로그인_후_화면들에_인라인_코드가_없다(auth_client):
    sid = create_subject(auth_client)
    assert sid == 1
    note = auth_client.post(
        f"/api/subjects/{sid}/notes", json={"kind": "remember", "title": "화면 검사"}
    )
    assert note.status_code == 201
    paths = ["/", "/subjects/1", "/subjects/1/notes/new", "/notes/1", "/notes/1/edit"]
    for path in paths:
        response = auth_client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path
        assert_no_inline_code(path, response.text)


def test_sec6_인라인_검사기가_위반을_실제로_잡는다():
    bad_pages = [
        "<script>alert(1)</script>",
        '<button onclick="x()">a</button>',
        '<div style="color:red">a</div>',
        "<img src=x onerror=x()>",
    ]
    for html in bad_pages:
        with pytest.raises(AssertionError):
            assert_no_inline_code("검사기", html)
    assert_no_inline_code(
        "검사기", '<script type="module" src="/static/js/a.js"></script><p>ok</p>'
    )


# ---------------------------------------------------------------------------
# SEC-6: 문서 주소 끔
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_sec6_문서_주소는_로그인_상태에서_404(auth_client, path):
    assert auth_client.get(path, follow_redirects=False).status_code == 404


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_sec6_문서_주소는_미로그인에서도_404(client, path):
    assert client.get(path, follow_redirects=False).status_code == 404


# ---------------------------------------------------------------------------
# SEC-6: 405, 잘못된 UTF-8 본문, 일반 예외
# ---------------------------------------------------------------------------


def test_sec6_DELETE_api_subjects는_405_Allow_헤더와_공통_오류_모양(auth_client):
    response = auth_client.delete("/api/subjects")
    assert_error_shape(response, 405)
    assert "detail" not in response.json()
    allow = response.headers.get("allow")
    assert allow and allow.strip(), "405에는 비어 있지 않은 Allow 헤더가 있어야 한다"


def test_sec6_미로그인_DELETE_api_subjects도_405(client):
    response = client.delete("/api/subjects")
    assert_error_shape(response, 405)
    assert response.headers.get("allow")


INVALID_UTF8_BODY = b'{"name":"\xff"}'


def test_sec6_잘못된_UTF8_본문은_미로그인이면_401(client):
    response = client.post("/api/subjects", content=INVALID_UTF8_BODY, headers=JSON_HEADERS)
    assert response.status_code == 401, response.text[:200]
    assert response.json() == UNAUTHORIZED_BODY


def test_sec6_잘못된_UTF8_본문은_로그인_상태면_422_fields_request(auth_client):
    response = auth_client.post("/api/subjects", content=INVALID_UTF8_BODY, headers=JSON_HEADERS)
    error = assert_validation_fields(response, "request")
    assert "name" not in error["fields"]


def test_sec6_login의_잘못된_UTF8_본문은_422_fields_request(client):
    body = b'{"password":"\xff"}'
    response = client.post("/api/login", content=body, headers=JSON_HEADERS)
    error = assert_validation_fields(response, "request")
    assert "password" not in error["fields"]
    assert response.headers.get_list("set-cookie") == []


def test_sec6_잘못된_UTF8_본문_PATCH도_로그인_상태면_422_fields_request(world):
    client = world["client"]
    response = client.patch(
        f"/api/subjects/{world['subject']}", content=INVALID_UTF8_BODY, headers=JSON_HEADERS
    )
    assert_validation_fields(response, "request")


def test_sec6_일반_예외는_500_공통_모양이고_예외_문구가_없고_보안_헤더가_붙는다(settings):
    secret_text = "SECRET-BOOM-MESSAGE-7731"

    def boom():
        raise RuntimeError(secret_text)

    app = create_app(settings)
    app.add_api_route("/api/_sec6_boom", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/login", json={"password": TEST_PASSWORD})
        response = client.get("/api/_sec6_boom")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR_BODY
    assert response.headers["content-type"].startswith("application/json")
    assert secret_text not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert_security_headers(response)


def test_sec6_일반_예외_500은_미로그인_경로에서도_같은_모양(settings):
    def boom():
        raise ValueError("another-secret-text")

    app = create_app(settings)
    app.add_api_route("/_sec6_boom_page", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_sec6_boom_page", follow_redirects=False)
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "일시적인 문제가 발생했습니다" in response.text
    assert "another-secret-text" not in response.text
    assert_security_headers(response)


def test_sec6_일반_예외_500은_API_경로면_no_store가_붙는다(settings):
    def boom():
        raise RuntimeError("cache-secret-text")

    app = create_app(settings)
    app.add_api_route("/api/_sec6_boom_cache", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/login", json={"password": TEST_PASSWORD})
        response = client.get("/api/_sec6_boom_cache")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR_BODY
    assert response.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# SEC-6: 보호 목록 자동 검사 (새 주소를 빠뜨려도 잡힌다)
# ---------------------------------------------------------------------------

OPEN_API_PATHS = {"/api/login", "/api/logout"}
OPEN_PAGE_PATHS = {"/login"}
BODY_METHODS = {"POST", "PATCH", "PUT"}


def fill_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "1", path)


def collect_routes(app):
    """(경로, 메서드) 목록을 api / page로 나눠 돌려준다. Mount는 따로 모은다."""
    api: list[tuple[str, str]] = []
    pages: list[tuple[str, str]] = []
    mounts: list[str] = []

    def walk(routes):
        for route in routes:
            if isinstance(route, Mount):
                mounts.append(route.path)
                continue
            # 이 FastAPI 버전은 include_router 결과를 중첩 라우터로 들고 있다.
            # 풀어 보면 prefix가 합쳐진 전체 경로를 가진 항목이 나온다.
            children = getattr(route, "effective_candidates", None)
            if callable(children):
                walk(children())
                continue
            target = getattr(route, "starlette_route", None) or route
            path = getattr(target, "path", None) or getattr(route, "path", None)
            methods = getattr(target, "methods", None) or getattr(route, "methods", None)
            if not path or not methods:
                continue
            for method in sorted(set(methods) - {"HEAD", "OPTIONS"}):
                if path.startswith("/api/") or path == "/api":
                    if path not in OPEN_API_PATHS:
                        api.append((path, method))
                elif path not in OPEN_PAGE_PATHS:
                    pages.append((path, method))

    walk(app.routes)
    return api, pages, mounts


def test_sec6_보호_목록_모든_API_경로와_메서드는_미로그인에서_401(client):
    api, _, _ = collect_routes(client.app)
    assert len(api) >= 14, f"API 경로가 너무 적게 잡혔다: {api}"
    failures = []
    for path, method in api:
        url = fill_path(path)
        if method in BODY_METHODS:
            response = client.request(method, url, json={})
        else:
            response = client.request(method, url)
        if response.status_code != 401:
            failures.append((method, path, response.status_code))
    assert not failures, f"미로그인에서 401이 아닌 API: {failures}"


def test_sec6_보호_목록_모든_화면_경로는_미로그인에서_302(client):
    _, pages, mounts = collect_routes(client.app)
    assert len(pages) >= 5, f"화면 경로가 너무 적게 잡혔다: {pages}"
    assert set(mounts) <= {"/static"}, f"새 Mount는 공개 여부를 정해야 한다: {mounts}"
    failures = []
    for path, method in pages:
        response = client.request(method, fill_path(path), follow_redirects=False)
        if response.status_code != 302 or response.headers.get("location") != "/login":
            failures.append((method, path, response.status_code))
    assert not failures, f"미로그인에서 /login으로 302가 아닌 화면: {failures}"


def test_sec6_보호_목록에_알려진_주소가_모두_들어_있다(client):
    api, pages, _ = collect_routes(client.app)
    api_found = {(fill_path(p), m) for p, m in api}
    assert ("/api/subjects", "GET") in api_found
    assert ("/api/subjects", "POST") in api_found
    assert ("/api/subjects/1/export", "GET") in api_found
    assert ("/api/notes/1", "DELETE") in api_found
    page_found = {fill_path(p) for p, _ in pages}
    assert {"/", "/subjects/1", "/subjects/1/notes/new", "/notes/1", "/notes/1/edit"} <= page_found


# ---------------------------------------------------------------------------
# SEC-6: DB 오류 로그에 파라미터를 남기지 않는다
# ---------------------------------------------------------------------------


def test_sec6_엔진은_hide_parameters가_켜져_있다(client):
    assert client.app.state.engine.hide_parameters is True
