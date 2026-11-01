"""예외 처리 기능(F7~F12) 계약 테스트. 이후 기능도 이 파일에 추가한다.

F7 렌더 실패 복구
완료 기준
- 본문이 `>` 50,000자인 노트를 S5에서 열면 제목, 수정·삭제 버튼, 본문 원문이 보이고
  "서식을 적용하지 못해 원문으로 표시합니다" 문구가 보인다. S4 미리보기도 같은 본문에서
  원문과 같은 문구를 보이고, "편집"을 누르면 입력이 그대로 있다. 렌더가 성공하는 본문은
  전과 같게 보인다.
  (렌더는 브라우저 JS 동작이라 pytest 대상이 아니다. 메인 세션이 실제 브라우저로 확인한다.
   여기서는 서버 쪽 약속만 확인한다: 저장·조회가 글자 하나 다르지 않게 되고,
   수정·삭제·내보내기가 되며, 화면 주소가 로그인 후 200 HTML이다.)

F10 저장소 장애 처리
완료 기준
- DB가 잠겨 있으면 5초쯤 뒤 503 `storage_busy`와 `retry_after`가 오고, 읽기 전용·용량 부족·
  테이블 없음이면 503 `storage_unavailable`이 온다. (S4 입력 유지·저장 버튼은 브라우저로 확인한다.)
- 어느 폴더에서 실행해도 같은 `.env`와 같은 DB를 쓴다.
- 빈 DB를 새로 만들면 경로가 든 경고가 로그에 남는다.
- 잘못된 설정이나 손상된 DB로 시작하면 "시작 실패:"로 시작하는 원인 한 줄이 로그에 남고
  프로세스가 0이 아닌 코드로 끝난다.
- 로그인: APP_PASSWORD나 SECRET_KEY가 비어 있으면 500 `server_misconfigured`.

해석
- 본문 최대 길이 50,000자는 그대로이고 50,001자는 전처럼 422(fields.body)다.
- F10 시작 시험은 모두 subprocess이고 항상 DATABASE_URL을 명시한다. data/study.db는 열지 않는다.
"""

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.settings import Settings

from .conftest import TEST_PASSWORD, make_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

MAX_BODY = 50_000
HOSTILE_BODY = ">" * MAX_BODY


def make_subject(client: TestClient, name: str = "렌더 실패 주제") -> int:
    response = client.post(
        "/api/subjects",
        json={"name": name, "background": "", "started_on": "2026-10-26"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def post_note(client: TestClient, subject_id: int, body: str, **fields):
    payload = {"kind": "remember", "title": "깊은 인용 노트", "body": body}
    payload.update(fields)
    return client.post(f"/api/subjects/{subject_id}/notes", json=payload)


def make_hostile_note(client: TestClient) -> tuple[int, dict]:
    sid = make_subject(client)
    response = post_note(client, sid, HOSTILE_BODY)
    assert response.status_code == 201, response.text[:300]
    return sid, response.json()


# ---------------------------------------------------------------------------
# F7: 저장과 조회
# ---------------------------------------------------------------------------


def test_f7_note_with_50000_gt_chars_is_created_with_201(auth_client: TestClient):
    sid = make_subject(auth_client)
    response = post_note(auth_client, sid, HOSTILE_BODY)
    assert response.status_code == 201, response.text[:300]
    data = response.json()
    assert len(data["body"]) == MAX_BODY
    assert data["body"] == HOSTILE_BODY
    assert data["title"] == "깊은 인용 노트"


def test_f7_get_returns_body_without_any_character_changed(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.get(f"/api/notes/{note['id']}")
    assert response.status_code == 200
    body = response.json()["body"]
    assert len(body) == MAX_BODY
    assert body == HOSTILE_BODY


def test_f7_body_of_50001_chars_is_422_as_before(auth_client: TestClient):
    sid = make_subject(auth_client)
    response = post_note(auth_client, sid, ">" * (MAX_BODY + 1))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "body" in error["fields"]


def test_f7_patch_body_of_50001_chars_is_422_and_note_is_kept(
    auth_client: TestClient,
):
    _, note = make_hostile_note(auth_client)
    response = auth_client.patch(
        f"/api/notes/{note['id']}", json={"body": ">" * (MAX_BODY + 1)}
    )
    assert response.status_code == 422
    assert "body" in response.json()["error"]["fields"]
    again = auth_client.get(f"/api/notes/{note['id']}")
    assert again.json()["body"] == HOSTILE_BODY


# ---------------------------------------------------------------------------
# F7: 렌더에 실패하는 노트도 고치고 지울 수 있다
# ---------------------------------------------------------------------------


def test_f7_patch_title_on_hostile_note_keeps_body(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.patch(
        f"/api/notes/{note['id']}", json={"title": "제목만 고침"}
    )
    assert response.status_code == 200, response.text[:300]
    data = response.json()
    assert data["title"] == "제목만 고침"
    assert data["body"] == HOSTILE_BODY


def test_f7_patch_body_replaces_hostile_body(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.patch(
        f"/api/notes/{note['id']}", json={"body": "# 고친 본문\n\n정상 마크다운"}
    )
    assert response.status_code == 200
    assert response.json()["body"] == "# 고친 본문\n\n정상 마크다운"
    again = auth_client.get(f"/api/notes/{note['id']}")
    assert again.json()["body"] == "# 고친 본문\n\n정상 마크다운"


def test_f7_patch_can_save_hostile_body_again(auth_client: TestClient):
    sid = make_subject(auth_client)
    created = post_note(auth_client, sid, "처음엔 정상").json()
    response = auth_client.patch(
        f"/api/notes/{created['id']}", json={"body": HOSTILE_BODY}
    )
    assert response.status_code == 200, response.text[:300]
    assert response.json()["body"] == HOSTILE_BODY


def test_f7_delete_hostile_note_is_204_and_then_404(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.delete(f"/api/notes/{note['id']}")
    assert response.status_code == 204
    assert auth_client.get(f"/api/notes/{note['id']}").status_code == 404


# ---------------------------------------------------------------------------
# F7: 내보내기
# ---------------------------------------------------------------------------


def test_f7_export_of_subject_with_hostile_note_is_200_with_raw_body(
    auth_client: TestClient,
):
    sid, _ = make_hostile_note(auth_client)
    response = auth_client.get(f"/api/subjects/{sid}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    text = response.content.decode("utf-8")
    assert "## 깊은 인용 노트" in text
    assert HOSTILE_BODY in text


# ---------------------------------------------------------------------------
# F7: 화면 주소
# ---------------------------------------------------------------------------


def test_f7_note_view_page_is_200_html_when_logged_in(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.get(f"/notes/{note['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f7_note_edit_page_is_200_html_when_logged_in(auth_client: TestClient):
    _, note = make_hostile_note(auth_client)
    response = auth_client.get(f"/notes/{note['id']}/edit")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_f7_note_pages_redirect_to_login_when_logged_out(client: TestClient):
    for path in ("/notes/1", "/notes/1/edit"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert response.headers["location"].startswith("/login"), path


def test_f7_normal_markdown_note_is_stored_as_before(auth_client: TestClient):
    sid = make_subject(auth_client)
    body = "# 제목\n\n> 인용 한 줄\n\n```python\nprint('hi')\n```\n"
    response = post_note(auth_client, sid, body)
    assert response.status_code == 201
    assert response.json()["body"] == body
    got = auth_client.get(f"/api/notes/{response.json()['id']}")
    assert got.json()["body"] == body


# ===========================================================================
# F10: 저장소 장애 처리
# ===========================================================================

BUSY_BODY = {
    "error": {
        "code": "storage_busy",
        "message": "저장소가 잠시 바쁩니다. 잠시 후 다시 시도하세요",
        "retry_after": 5,
    }
}
UNAVAILABLE_BODY = {
    "error": {
        "code": "storage_unavailable",
        "message": "저장소에 문제가 있어 처리하지 못했습니다",
    }
}

# 응답에 들어가면 안 되는 말(SQL, 예외 문구, 경로 조각). 소문자로 비교한다.
LEAK_WORDS = [
    "sqlite",
    "select ",
    "insert ",
    "update ",
    "traceback",
    "operationalerror",
    "no such table",
    "readonly",
    "read-only",
    "disk is full",
    "locked",
    "unable to open",
    ".db",
]


@dataclass
class Storage:
    """파일 DB 위에서 로그인까지 마친 클라이언트와 미리 만든 자원."""

    app: FastAPI
    client: TestClient
    db: Path
    tmp_path: Path
    subject_id: int
    note_id: int


def assert_no_leak(response, *extra: str) -> None:
    text = response.text.lower()
    for word in [*LEAK_WORDS, *[e.lower() for e in extra]]:
        assert word not in text, f"응답에 {word!r}가 들어 있다: {response.text}"


def assert_503(response, expected: dict, *, tmp_path: Path) -> None:
    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == expected
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert_no_leak(response, str(tmp_path))
    if expected["error"]["code"] == "storage_busy":
        assert response.headers.get("retry-after") == "5"
    else:
        assert "retry-after" not in response.headers
        assert "retry_after" not in response.json()["error"]


@pytest.fixture
def storage(tmp_path: Path):
    db = tmp_path / "x.db"
    app = create_app(make_settings(database_url="sqlite:///" + str(db)))
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/api/login", json={"password": TEST_PASSWORD})
        assert login.status_code == 204, login.text
        sid = make_subject(client, "저장소 장애 주제")
        note = post_note(client, sid, "처음 본문")
        assert note.status_code == 201, note.text
        yield Storage(app, client, db, tmp_path, sid, note.json()["id"])


def new_subject_payload(name: str = "새 주제") -> dict:
    return {"name": name, "background": "", "started_on": "2026-10-26"}


def subject_count(client: TestClient) -> int:
    response = client.get("/api/subjects")
    assert response.status_code == 200, response.text
    return len(response.json()["items"])


def user_tables(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def rename_tables(db: Path, *, away: bool) -> None:
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        for name in user_tables(db):
            if away and not name.endswith("_gone"):
                conn.execute(f'ALTER TABLE "{name}" RENAME TO "{name}_gone"')
            elif not away and name.endswith("_gone"):
                conn.execute(f'ALTER TABLE "{name}" RENAME TO "{name[: -len("_gone")]}"')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# F10: 잠금 -> 503 storage_busy (약 5초 걸리므로 한 번만 시험한다)
# ---------------------------------------------------------------------------


def test_f10_locked_db_gives_503_storage_busy_after_about_5_seconds(storage: Storage):
    before = subject_count(storage.client)
    locker = sqlite3.connect(storage.db, timeout=0, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        # 잠겨 있어도 읽기는 막히지 않는다.
        assert storage.client.get("/api/subjects").status_code == 200

        started = time.monotonic()
        response = storage.client.post("/api/subjects", json=new_subject_payload("잠긴 동안"))
        elapsed = time.monotonic() - started
    finally:
        locker.rollback()
        locker.close()

    assert 3.5 <= elapsed < 12, f"5초쯤 기다린 뒤 실패해야 한다: {elapsed:.1f}초"
    assert_503(response, BUSY_BODY, tmp_path=storage.tmp_path)
    assert response.json()["error"]["retry_after"] == 5
    assert "fields" not in response.json()["error"]

    # 잠금이 풀리면 같은 요청이 그대로 성공하고, 실패한 요청은 저장되지 않았다.
    assert subject_count(storage.client) == before
    retry = storage.client.post("/api/subjects", json=new_subject_payload("잠금 해제 뒤"))
    assert retry.status_code == 201, retry.text
    assert subject_count(storage.client) == before + 1


# ---------------------------------------------------------------------------
# F10: 읽기 전용 -> 503 storage_unavailable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root는 파일 권한을 무시한다",
)
def test_f10_read_only_db_gives_503_storage_unavailable_and_recovers(storage: Storage):
    before = subject_count(storage.client)
    storage.app.state.engine.dispose()
    os.chmod(storage.db, 0o444)
    try:
        response = storage.client.post(
            "/api/subjects", json=new_subject_payload("읽기 전용")
        )
        assert_503(response, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)

        patch = storage.client.patch(
            f"/api/subjects/{storage.subject_id}", json={"name": "바꾸기"}
        )
        assert_503(patch, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)

        delete = storage.client.delete(f"/api/notes/{storage.note_id}")
        assert_503(delete, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)
    finally:
        os.chmod(storage.db, 0o644)
        storage.app.state.engine.dispose()

    assert subject_count(storage.client) == before
    assert storage.client.get(f"/api/notes/{storage.note_id}").status_code == 200
    again = storage.client.post("/api/subjects", json=new_subject_payload("복구 뒤"))
    assert again.status_code == 201, again.text


# ---------------------------------------------------------------------------
# F10: 용량 부족 -> 503 storage_unavailable
# ---------------------------------------------------------------------------


def test_f10_disk_full_gives_503_storage_unavailable_and_recovers(storage: Storage):
    conn = sqlite3.connect(storage.db)
    try:
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
    finally:
        conn.close()

    def limit_pages(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"PRAGMA max_page_count = {pages + 1}")
        cursor.close()

    engine = storage.app.state.engine
    event.listen(engine, "connect", limit_pages)
    engine.dispose()
    try:
        response = storage.client.post(
            f"/api/subjects/{storage.subject_id}/notes",
            json={"kind": "remember", "title": "큰 노트", "body": "x" * MAX_BODY},
        )
        assert_503(response, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)

        # 읽기는 그대로 되고, 실패한 노트는 남지 않는다.
        listing = storage.client.get(f"/api/subjects/{storage.subject_id}/notes")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
    finally:
        event.remove(engine, "connect", limit_pages)
        engine.dispose()

    again = storage.client.post(
        f"/api/subjects/{storage.subject_id}/notes",
        json={"kind": "remember", "title": "큰 노트", "body": "x" * MAX_BODY},
    )
    assert again.status_code == 201, again.text[:300]


# ---------------------------------------------------------------------------
# F10: 테이블 없음 -> 503 storage_unavailable
# ---------------------------------------------------------------------------


def test_f10_missing_tables_give_503_on_read_and_write_apis(storage: Storage):
    rename_tables(storage.db, away=True)
    sid, nid = storage.subject_id, storage.note_id
    requests = [
        ("get", "/api/subjects", None),
        ("post", "/api/subjects", new_subject_payload("없는 테이블")),
        ("get", f"/api/subjects/{sid}", None),
        ("patch", f"/api/subjects/{sid}", {"name": "바꾸기"}),
        ("get", f"/api/subjects/{sid}/sessions", None),
        (
            "post",
            f"/api/subjects/{sid}/sessions",
            {"studied_on": "2026-10-30", "minutes": 30, "memo": ""},
        ),
        ("get", f"/api/subjects/{sid}/notes", None),
        ("post", f"/api/subjects/{sid}/notes", {"kind": "remember", "title": "t", "body": "b"}),
        ("get", f"/api/notes/{nid}", None),
        ("patch", f"/api/notes/{nid}", {"title": "바꾸기"}),
        ("delete", f"/api/notes/{nid}", None),
        ("get", f"/api/subjects/{sid}/export", None),
    ]
    try:
        for method, path, payload in requests:
            kwargs = {"json": payload} if payload is not None else {}
            response = getattr(storage.client, method)(path, **kwargs)
            assert_503(response, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)
    finally:
        rename_tables(storage.db, away=False)

    assert storage.client.get(f"/api/notes/{nid}").status_code == 200
    assert subject_count(storage.client) == 1


def test_f10_503_requires_login_first_401_is_not_replaced(storage: Storage):
    rename_tables(storage.db, away=True)
    try:
        anonymous = TestClient(storage.app, raise_server_exceptions=False)
        response = anonymous.get("/api/subjects")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    finally:
        rename_tables(storage.db, away=False)


def test_f10_error_details_go_to_the_server_log_but_bind_values_do_not(
    storage: Storage, caplog: pytest.LogCaptureFixture
):
    secret_name = "바인딩비밀값-XYZ-12345"
    rename_tables(storage.db, away=True)
    try:
        with caplog.at_level("DEBUG"):
            response = storage.client.post(
                "/api/subjects", json=new_subject_payload(secret_name)
            )
    finally:
        rename_tables(storage.db, away=False)
    assert_503(response, UNAVAILABLE_BODY, tmp_path=storage.tmp_path)
    assert secret_name not in response.text
    assert secret_name not in caplog.text
    assert any(r.levelname in ("WARNING", "ERROR", "CRITICAL") for r in caplog.records), (
        "DB 오류는 서버 로그에 남아야 한다"
    )


# ---------------------------------------------------------------------------
# F10: DB 오류만 503이고 그 밖의 예외는 500 internal_error 그대로
# ---------------------------------------------------------------------------


def test_f10_non_db_exception_stays_500_internal_error(tmp_path: Path):
    app = create_app(make_settings(database_url="sqlite:///" + str(tmp_path / "x.db")))

    @app.get("/api/_f10_boom")
    def boom():
        # 문구가 DB 오류처럼 보여도 SQLAlchemy 예외가 아니면 503으로 바꾸지 않는다.
        raise RuntimeError("database is locked")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 204
        response = client.get("/api/_f10_boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "database is locked" not in response.text


def test_f10_sqlalchemy_error_is_503_without_sql_or_bind_values(tmp_path: Path):
    app = create_app(make_settings(database_url="sqlite:///" + str(tmp_path / "x.db")))

    @app.get("/api/_f10_dberror")
    def dberror():
        raise OperationalError(
            "INSERT INTO subjects (name) VALUES (?)",
            ("바인딩비밀값",),
            Exception("disk I/O error"),
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 204
        response = client.get("/api/_f10_dberror")
    assert_503(response, UNAVAILABLE_BODY, tmp_path=tmp_path)
    assert "바인딩비밀값" not in response.text
    assert "disk i/o" not in response.text.lower()


# ---------------------------------------------------------------------------
# F10: 로그인 설정 오류 500 server_misconfigured
# ---------------------------------------------------------------------------

MISCONFIGURED_BODY = {
    "error": {"code": "server_misconfigured", "message": "서버 설정이 올바르지 않습니다"}
}


@pytest.mark.parametrize(
    "overrides",
    [{"app_password": ""}, {"secret_key": ""}, {"app_password": "", "secret_key": ""}],
    ids=["empty-password", "empty-secret-key", "both-empty"],
)
def test_f10_login_is_500_server_misconfigured_when_setting_is_empty(overrides: dict):
    app = create_app(make_settings(**overrides))
    with TestClient(app, raise_server_exceptions=False) as client:
        for password in (TEST_PASSWORD, "wrong-password", "x"):
            response = client.post("/api/login", json={"password": password})
            assert response.status_code == 500, response.text
            assert response.json() == MISCONFIGURED_BODY
            assert "set-cookie" not in response.headers
            assert response.headers.get("x-content-type-options") == "nosniff"


def test_f10_login_misconfigured_is_not_counted_as_failed_attempt():
    app = create_app(make_settings(secret_key=""))
    with TestClient(app, raise_server_exceptions=False) as client:
        # 5회 연속 실패 뒤에 429가 되는 규칙에 걸리지 않는다.
        for _ in range(8):
            response = client.post("/api/login", json={"password": "wrong-password"})
            assert response.status_code == 500, response.text
            assert response.json()["error"]["code"] == "server_misconfigured"


def test_f10_login_still_works_and_rejects_wrong_password_when_configured():
    app = create_app(make_settings())
    with TestClient(app) as client:
        wrong = client.post("/api/login", json={"password": "wrong-password"})
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "invalid_password"
        ok = client.post("/api/login", json={"password": TEST_PASSWORD})
        assert ok.status_code == 204


# ---------------------------------------------------------------------------
# F10: 서버 시작 규칙 (subprocess)
#
# 실제 데이터 보호: 모든 subprocess에 DATABASE_URL을 명시한다. data/study.db는 열지 않는다.
# ---------------------------------------------------------------------------

START_PASSWORD = "start-pass-Q7Zk-9931"
START_SECRET = "start-secret-Q7Zk-9931"
EMPTY_DB_WARNING = "새 빈 DB를 만들었습니다: "
EMPTY_DB_ADVICE = "기존 데이터가 있었다면 서버를 멈추고 DATABASE_URL과 백업을 확인하세요"

DRIVER = r"""
import json, logging, os, sys
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
from fastapi.testclient import TestClient
from app.main import app

mode = sys.argv[1]
with TestClient(app) as client:
    if mode == "start":
        print("started")
    else:
        r = client.post("/api/login", json={"password": os.environ["APP_PASSWORD"]})
        assert r.status_code == 204, r.text
        if mode == "create":
            r = client.post(
                "/api/subjects",
                json={"name": "폴더 시험", "background": "", "started_on": "2026-10-26"},
            )
            assert r.status_code == 201, r.text
            print("created")
        elif mode == "count":
            r = client.get("/api/subjects")
            assert r.status_code == 200, r.text
            print(len(r.json()["items"]))
"""


def run_server(
    database_url: str,
    cwd: Path,
    mode: str = "start",
    **env_overrides: str,
) -> subprocess.CompletedProcess:
    """앱을 시작시켰다 끝내는 새 프로세스. DATABASE_URL 없이는 실행하지 않는다."""
    assert database_url, "DATABASE_URL을 반드시 명시한다"
    assert "data/study.db" not in database_url, "실제 데이터 DB는 쓰지 않는다"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": database_url,
            "APP_PASSWORD": START_PASSWORD,
            "SECRET_KEY": START_SECRET,
            "PUBLIC_DEPLOY": "false",
            "PYTHONPATH": str(SRC_DIR),
        }
    )
    env.update(env_overrides)
    cwd.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-c", DRIVER, mode],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def abs_url(path: Path) -> str:
    return "sqlite:///" + str(path)


def failure_lines(proc: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in proc.stderr.splitlines() if ln.startswith("시작 실패:")]


def assert_start_failed(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode != 0, f"0이 아닌 종료 코드여야 한다\n{proc.stderr}"
    lines = failure_lines(proc)
    assert len(lines) == 1, f"'시작 실패:' 줄이 정확히 한 줄이어야 한다\n{proc.stderr}"
    assert START_PASSWORD not in proc.stderr
    assert START_SECRET not in proc.stderr
    assert "started" not in proc.stdout
    return lines[0]


# --- 시작 실패 네 가지 ------------------------------------------------------


def test_f10_start_fails_with_one_line_when_env_value_has_wrong_format(tmp_path: Path):
    db = tmp_path / "ok.db"
    proc = run_server(abs_url(db), tmp_path / "cwd", PUBLIC_DEPLOY="maybe-not-a-bool")
    line = assert_start_failed(proc)
    assert "설정" in line
    assert "값이 올바르지 않습니다" in line
    assert "public_deploy" in line.lower()
    # 설정값 자체는 한 줄에 담지 않는다.
    assert "maybe-not-a-bool" not in line


@pytest.mark.parametrize(
    "bad_url",
    ["this-is-not-a-url-ZZTOP", "nodriver+fakedb://host/ZZTOP"],
    ids=["malformed-url", "missing-driver"],
)
def test_f10_start_fails_when_database_url_is_malformed_or_driver_is_missing(
    tmp_path: Path, bad_url: str
):
    proc = run_server(bad_url, tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.strip() == "시작 실패: DATABASE_URL을 확인하세요"
    assert "ZZTOP" not in line


def test_f10_start_fails_when_db_folder_cannot_be_created(tmp_path: Path):
    blocker = tmp_path / "afile"
    blocker.write_text("일반 파일이라 아래에 폴더를 만들 수 없다")
    db = blocker / "sub" / "study.db"
    proc = run_server(abs_url(db), tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.startswith("시작 실패: DB를 열 수 없습니다: ")
    assert str(db) in line
    assert line.rstrip().endswith("폴더 권한을 확인하세요")
    assert not db.exists()


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root는 파일 권한을 무시한다",
)
def test_f10_start_fails_when_db_file_is_not_writable(tmp_path: Path):
    db = tmp_path / "db" / "study.db"
    first = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert first.returncode == 0, first.stderr
    os.chmod(db, 0o444)
    try:
        proc = run_server(abs_url(db), tmp_path / "cwd")
    finally:
        os.chmod(db, 0o644)
    line = assert_start_failed(proc)
    assert line.startswith("시작 실패: DB를 열 수 없습니다: ")
    assert str(db) in line
    assert line.rstrip().endswith("폴더 권한을 확인하세요")


def test_f10_start_fails_when_db_file_is_not_sqlite(tmp_path: Path):
    db = tmp_path / "study.db"
    original = ("SQLite가 아닌 내용입니다. " * 200).encode("utf-8")
    db.write_bytes(original)
    proc = run_server(abs_url(db), tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.startswith("시작 실패: DB 파일이 손상되었습니다: ")
    assert str(db) in line
    assert line.rstrip().endswith("백업으로 복원하세요")
    # 손상된 파일을 덮어쓰지 않는다.
    assert db.read_bytes() == original
    assert EMPTY_DB_WARNING not in proc.stderr


def test_f10_start_fails_when_db_file_is_truncated_sqlite(tmp_path: Path):
    db = tmp_path / "study.db"
    first = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert first.returncode == 0, first.stderr
    data = db.read_bytes()
    assert data.startswith(b"SQLite format 3")
    # 헤더는 남기고 뒤쪽을 쓰레기로 바꾼다.
    db.write_bytes(data[:100] + b"\xff" * (len(data) - 100))
    proc = run_server(abs_url(db), tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.startswith("시작 실패: DB 파일이 손상되었습니다: ")
    assert str(db) in line


# --- 빈 DB 경고 ---------------------------------------------------------------


def test_f10_new_empty_db_is_created_with_warning_that_has_absolute_path(tmp_path: Path):
    db = (tmp_path / "newdir" / "study.db").resolve()
    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert "started" in proc.stdout
    expected = f"{EMPTY_DB_WARNING}{db}. {EMPTY_DB_ADVICE}"
    assert expected in proc.stderr, proc.stderr
    assert db.exists() and db.stat().st_size > 0
    assert failure_lines(proc) == []


def test_f10_zero_byte_db_file_also_gets_the_warning_and_start_continues(tmp_path: Path):
    db = (tmp_path / "study.db").resolve()
    db.write_bytes(b"")
    proc = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert proc.returncode == 0, proc.stderr
    assert f"{EMPTY_DB_WARNING}{db}. {EMPTY_DB_ADVICE}" in proc.stderr
    assert "created" in proc.stdout


def test_f10_existing_db_with_data_starts_without_the_empty_db_warning(tmp_path: Path):
    db = (tmp_path / "study.db").resolve()
    first = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert first.returncode == 0, first.stderr
    assert EMPTY_DB_WARNING in first.stderr
    second = run_server(abs_url(db), tmp_path / "cwd", "count")
    assert second.returncode == 0, second.stderr
    assert EMPTY_DB_WARNING not in second.stderr
    assert second.stdout.strip().splitlines()[-1] == "1"


def test_f10_in_memory_db_has_no_empty_db_warning(tmp_path: Path):
    proc = run_server("sqlite:///:memory:", tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert EMPTY_DB_WARNING not in proc.stderr
    assert failure_lines(proc) == []


# --- 어느 폴더에서 실행해도 같은 .env와 같은 DB ----------------------------------


def test_f10_env_file_setting_points_to_project_root_env_with_absolute_path():
    env_file = Settings.model_config["env_file"]
    candidates = [env_file] if isinstance(env_file, (str, Path)) else list(env_file)
    assert candidates, "env_file이 설정되어 있어야 한다"
    paths = [Path(c) for c in candidates]
    assert all(p.is_absolute() for p in paths), paths
    assert (PROJECT_ROOT / ".env").resolve() in [p.resolve() for p in paths], paths


def test_f10_absolute_database_url_is_used_as_is_from_any_folder(tmp_path: Path):
    db = (tmp_path / "elsewhere-db" / "abs.db").resolve()
    cwd_a = tmp_path / "cwd-a"
    cwd_b = tmp_path / "cwd-b"
    first = run_server(abs_url(db), cwd_a, "create")
    assert first.returncode == 0, first.stderr
    second = run_server(abs_url(db), cwd_b, "count")
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip().splitlines()[-1] == "1"
    assert db.exists()
    # 실행한 폴더에는 아무 파일도 생기지 않는다.
    assert list(cwd_a.iterdir()) == []
    assert list(cwd_b.iterdir()) == []


def test_f10_relative_database_url_is_based_on_project_folder_not_cwd(tmp_path: Path):
    rel_dir = f".pytest-relative-{uuid.uuid4().hex}"
    in_project = PROJECT_ROOT / rel_dir
    assert not in_project.exists()
    url = f"sqlite:///{rel_dir}/study.db"
    cwd_a = tmp_path / "cwd-a"
    cwd_b = tmp_path / "cwd-b"
    try:
        first = run_server(url, cwd_a, "create")
        assert first.returncode == 0, first.stderr
        assert (in_project / "study.db").is_file()
        assert f"{EMPTY_DB_WARNING}{in_project / 'study.db'}." in first.stderr
        assert not (cwd_a / rel_dir).exists()
        assert list(cwd_a.iterdir()) == []

        # 다른 폴더에서 같은 상대 경로로 시작하면 같은 DB다(빈 DB 경고 없음, 데이터 그대로).
        second = run_server(url, cwd_b, "count")
        assert second.returncode == 0, second.stderr
        assert EMPTY_DB_WARNING not in second.stderr
        assert second.stdout.strip().splitlines()[-1] == "1"
        assert list(cwd_b.iterdir()) == []
    finally:
        shutil.rmtree(in_project, ignore_errors=True)
    assert not in_project.exists()


def test_f10_relative_database_url_failure_line_names_project_based_path(tmp_path: Path):
    rel_dir = f".pytest-relative-{uuid.uuid4().hex}"
    in_project = PROJECT_ROOT / rel_dir
    assert not in_project.exists()
    try:
        in_project.mkdir()
        (in_project / "study.db").write_bytes(("손상" * 500).encode("utf-8"))
        proc = run_server(f"sqlite:///{rel_dir}/study.db", tmp_path / "cwd")
        line = assert_start_failed(proc)
        assert line.startswith("시작 실패: DB 파일이 손상되었습니다: ")
        assert str(in_project / "study.db") in line
    finally:
        shutil.rmtree(in_project, ignore_errors=True)
    assert not in_project.exists()


# --- 시작 실패 로그에 비밀이 없다 -----------------------------------------------


def test_f10_start_failure_log_has_no_password_secret_or_database_url_value(
    tmp_path: Path,
):
    db = tmp_path / "study.db"
    db.write_bytes(("SQLite 아님 " * 300).encode("utf-8"))
    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert_start_failed(proc)
    line = failure_lines(proc)[0]
    assert "sqlite:///" not in line
    assert START_PASSWORD not in proc.stdout + proc.stderr
    assert START_SECRET not in proc.stdout + proc.stderr


# --- 쓸 수 없는 DB 폴더 ----------------------------------------------------------


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root는 파일 권한을 무시한다",
)
def test_f10_start_fails_when_db_folder_is_read_only_even_if_db_file_is_writable(
    tmp_path: Path,
):
    db_dir = (tmp_path / "ro").resolve()
    db = db_dir / "study.db"
    first = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert first.returncode == 0, first.stderr
    assert os.access(db, os.W_OK), "파일 자체는 쓸 수 있어야 이 시험이 의미가 있다"
    before_bytes = db.read_bytes()
    before_names = sorted(p.name for p in db_dir.iterdir())

    os.chmod(db_dir, 0o555)
    try:
        proc = run_server(abs_url(db), tmp_path / "cwd")
    finally:
        os.chmod(db_dir, 0o755)

    line = assert_start_failed(proc)
    assert line.strip() == f"시작 실패: DB를 열 수 없습니다: {db}. 폴더 권한을 확인하세요"
    # 실패한 시작이 DB를 건드리지 않는다.
    assert db.read_bytes() == before_bytes
    assert sorted(p.name for p in db_dir.iterdir()) == before_names
    assert EMPTY_DB_WARNING not in proc.stderr

    # 권한을 되돌리면 같은 DB로 다시 시작된다.
    again = run_server(abs_url(db), tmp_path / "cwd", "count")
    assert again.returncode == 0, again.stderr
    assert again.stdout.strip().splitlines()[-1] == "1"


# --- 새로 만든 폴더와 파일의 권한 ------------------------------------------------


def test_f10_newly_created_db_folder_is_700_and_db_file_is_600(tmp_path: Path):
    folder = (tmp_path / "fresh").resolve()
    db = folder / "study.db"
    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert mode_of(folder) == 0o700, oct(mode_of(folder))
    assert mode_of(db) == 0o600, oct(mode_of(db))


def test_f10_every_folder_created_for_a_nested_db_path_is_700(tmp_path: Path):
    top = (tmp_path / "level1").resolve()
    mid = top / "level2"
    leaf = mid / "level3"
    db = leaf / "study.db"
    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    for folder in (top, mid, leaf):
        assert folder.is_dir(), folder
        assert mode_of(folder) == 0o700, f"{folder}: {oct(mode_of(folder))}"
    assert mode_of(db) == 0o600, oct(mode_of(db))


def test_f10_new_db_file_stays_600_after_the_app_writes_data(tmp_path: Path):
    folder = (tmp_path / "written").resolve()
    db = folder / "study.db"
    proc = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert proc.returncode == 0, proc.stderr
    assert mode_of(folder) == 0o700, oct(mode_of(folder))
    assert mode_of(db) == 0o600, oct(mode_of(db))


def test_f10_new_db_file_in_existing_folder_is_600_and_folder_is_unchanged(
    tmp_path: Path,
):
    folder = (tmp_path / "existing").resolve()
    folder.mkdir()
    os.chmod(folder, 0o755)
    db = folder / "study.db"
    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert mode_of(folder) == 0o755, oct(mode_of(folder))
    assert mode_of(db) == 0o600, oct(mode_of(db))


# --- 이미 있는 폴더와 파일의 권한과 내용은 그대로 -----------------------------------


@pytest.mark.parametrize(
    ("dir_mode", "file_mode"),
    [(0o755, 0o644), (0o750, 0o640)],
    ids=["755-644", "750-640"],
)
def test_f10_existing_folder_and_db_file_keep_permissions_and_bytes(
    tmp_path: Path, dir_mode: int, file_mode: int
):
    folder = (tmp_path / "keep").resolve()
    db = folder / "study.db"
    first = run_server(abs_url(db), tmp_path / "cwd", "create")
    assert first.returncode == 0, first.stderr
    os.chmod(folder, dir_mode)
    os.chmod(db, file_mode)
    before = db.read_bytes()
    assert before.startswith(b"SQLite format 3")

    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert EMPTY_DB_WARNING not in proc.stderr
    assert mode_of(folder) == dir_mode, oct(mode_of(folder))
    assert mode_of(db) == file_mode, oct(mode_of(db))
    assert db.read_bytes() == before


def test_f10_existing_zero_byte_db_file_keeps_its_permissions(tmp_path: Path):
    folder = (tmp_path / "zero").resolve()
    folder.mkdir()
    os.chmod(folder, 0o755)
    db = folder / "study.db"
    db.write_bytes(b"")
    os.chmod(db, 0o644)

    proc = run_server(abs_url(db), tmp_path / "cwd")
    assert proc.returncode == 0, proc.stderr
    assert f"{EMPTY_DB_WARNING}{db}. {EMPTY_DB_ADVICE}" in proc.stderr
    assert mode_of(folder) == 0o755, oct(mode_of(folder))
    assert mode_of(db) == 0o644, oct(mode_of(db))


# --- DATABASE_URL의 쿼리·포트 값이 틀림 ----------------------------------------------


def test_f10_start_fails_when_database_url_query_value_is_wrong(tmp_path: Path):
    db = (tmp_path / "query" / "study.db").resolve()
    proc = run_server(f"sqlite:///{db}?timeout=TOPSECRETVALUE", tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.strip() == "시작 실패: DATABASE_URL을 확인하세요"
    assert "TOPSECRET" not in proc.stdout + proc.stderr
    assert not db.exists()


def test_f10_start_fails_when_database_url_port_is_not_a_number(tmp_path: Path):
    proc = run_server("postgresql://u:TOPSECRETPW@h:badport/db", tmp_path / "cwd")
    line = assert_start_failed(proc)
    assert line.strip() == "시작 실패: DATABASE_URL을 확인하세요"
    assert "TOPSECRET" not in proc.stdout + proc.stderr


# --- 시드 스크립트도 프로젝트 폴더 기준, 이름은 그대로 ---------------------------------


def test_f10_seed_script_relative_url_keeps_literal_folder_name_without_percent_encoding(
    tmp_path: Path,
):
    prefix = f".pytest-relative-{uuid.uuid4().hex}"
    folder_name = f"{prefix} 한글"
    real_folder = PROJECT_ROOT / folder_name
    encoded_folder = PROJECT_ROOT / quote(folder_name)
    assert encoded_folder.name != folder_name
    assert not real_folder.exists() and not encoded_folder.exists()
    db = real_folder / "sub" / "study.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{folder_name}/sub/study.db"
    env.setdefault("APP_PASSWORD", TEST_PASSWORD)
    env.setdefault("SECRET_KEY", "test-secret-key")
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/seed_bigdata.py"],
            env=env,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

        # 이름 그대로의 폴더에 DB가 생긴다.
        assert real_folder.is_dir()
        assert db.is_file() and db.stat().st_size > 0

        # 퍼센트 인코딩된 이름의 폴더(또는 같은 접두사의 다른 폴더)는 생기지 않는다.
        assert not encoded_folder.exists()
        siblings = sorted(p.name for p in PROJECT_ROOT.glob(f"{prefix}*"))
        assert siblings == [folder_name], siblings
        assert not any("%" in p.name for p in PROJECT_ROOT.iterdir() if prefix in p.name)

        # 데이터가 그 DB에 들어 있다.
        app = create_app(make_settings(database_url=abs_url(db)))
        with TestClient(app) as client:
            login = client.post("/api/login", json={"password": TEST_PASSWORD})
            assert login.status_code == 204, login.text
            subjects = client.get("/api/subjects")
            assert subjects.status_code == 200, subjects.text
            items = subjects.json()["items"]
            assert len(items) == 1
            assert items[0]["name"] == "빅데이터분석기사 실기"
            assert items[0]["note_count"] == 6
    finally:
        shutil.rmtree(real_folder, ignore_errors=True)
        shutil.rmtree(encoded_folder, ignore_errors=True)
        for leftover in PROJECT_ROOT.glob(f"{prefix}*"):
            shutil.rmtree(leftover, ignore_errors=True)
    assert not real_folder.exists() and not encoded_folder.exists()


# --- 시드 스크립트도 앱과 같은 저장소 열기 경로를 쓴다 ---------------------------------
#
# F10 해석: 시드 스크립트를 앱보다 먼저 돌려도 새 폴더는 700, 새 파일은 600이다.
# 모든 실행에 임시 절대 경로 DATABASE_URL을 명시한다. data/study.db는 열지 않는다.


def run_seed(database_url: str) -> subprocess.CompletedProcess:
    """시드 스크립트를 새 프로세스로 실행한다. DATABASE_URL 없이는 실행하지 않는다."""
    assert database_url, "DATABASE_URL을 반드시 명시한다"
    assert "data/study.db" not in database_url, "실제 데이터 DB는 쓰지 않는다"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": database_url,
            "APP_PASSWORD": START_PASSWORD,
            "SECRET_KEY": START_SECRET,
            "PUBLIC_DEPLOY": "false",
        }
    )
    return subprocess.run(
        [sys.executable, "scripts/seed_bigdata.py"],
        env=env,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def seeded_subjects(db: Path) -> list[dict]:
    """DB를 앱으로 열어 주제 목록을 읽는다(읽기만 한다)."""
    app = create_app(make_settings(database_url=abs_url(db)))
    with TestClient(app) as client:
        login = client.post("/api/login", json={"password": TEST_PASSWORD})
        assert login.status_code == 204, login.text
        response = client.get("/api/subjects")
        assert response.status_code == 200, response.text
        return response.json()["items"]


def test_f10_seed_script_on_missing_folders_creates_700_folders_and_600_db_with_data(
    tmp_path: Path,
):
    top = (tmp_path / "seed-level1").resolve()
    leaf = top / "seed-level2"
    db = leaf / "study.db"
    assert not top.exists()

    proc = run_seed(abs_url(db))
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # 만든 폴더는 모두 700, DB 파일은 600이다.
    for folder in (top, leaf):
        assert folder.is_dir(), folder
        assert mode_of(folder) == 0o700, f"{folder}: {oct(mode_of(folder))}"
    assert db.is_file() and db.stat().st_size > 0
    assert mode_of(db) == 0o600, oct(mode_of(db))

    # 시드 데이터가 들어 있다.
    items = seeded_subjects(db)
    assert len(items) == 1
    assert items[0]["name"] == "빅데이터분석기사 실기"
    assert items[0]["note_count"] == 6

    # 읽고 난 뒤에도 권한은 그대로다.
    for folder in (top, leaf):
        assert mode_of(folder) == 0o700, f"{folder}: {oct(mode_of(folder))}"
    assert mode_of(db) == 0o600, oct(mode_of(db))


def test_f10_app_start_after_seed_keeps_permissions_and_data_without_empty_db_warning(
    tmp_path: Path,
):
    folder = (tmp_path / "seed-then-app").resolve()
    db = folder / "study.db"
    seed = run_seed(abs_url(db))
    assert seed.returncode == 0, seed.stdout + seed.stderr
    assert mode_of(folder) == 0o700, oct(mode_of(folder))
    assert mode_of(db) == 0o600, oct(mode_of(db))
    before = db.read_bytes()
    assert before.startswith(b"SQLite format 3")

    # 같은 DB로 앱을 시작한다(이 실행에서 주제 수를 읽는다).
    proc = run_server(abs_url(db), tmp_path / "cwd", "count")
    assert proc.returncode == 0, proc.stderr
    assert failure_lines(proc) == []
    assert EMPTY_DB_WARNING not in proc.stderr, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "1"

    # 권한과 내용은 그대로다.
    assert mode_of(folder) == 0o700, oct(mode_of(folder))
    assert mode_of(db) == 0o600, oct(mode_of(db))
    assert db.read_bytes() == before

    # 시드 데이터가 그대로 보인다.
    items = seeded_subjects(db)
    assert len(items) == 1
    assert items[0]["name"] == "빅데이터분석기사 실기"
    assert items[0]["note_count"] == 6


def test_f10_seed_script_fails_when_database_url_query_value_is_wrong(tmp_path: Path):
    db = (tmp_path / "seed-query" / "study.db").resolve()
    proc = run_seed(f"sqlite:///{db}?timeout=TOPSECRETVALUE")
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"0이 아닌 종료 코드여야 한다\n{output}"
    assert "topsecret" not in output.lower(), output
    assert START_PASSWORD not in output
    assert START_SECRET not in output
    assert not db.exists()


# ===========================================================================
# F11: 화면 공통 오류 처리 (S6 오류 화면)
#
# 브라우저 동작(15초 시간 제한, 비JSON 응답, 로그아웃 실패, 로그인 잠금 문구, 요약 실패)은
# 메인 세션이 실제 브라우저로 확인한다. 여기서는 S6의 상태 코드와 내용만 확인한다.
# ===========================================================================

F11_NOT_FOUND_TITLE = "페이지를 찾을 수 없습니다"
F11_NOT_FOUND_HINT = "주소를 확인해 주세요"
F11_ERROR_TITLE = "일시적인 문제가 발생했습니다"
F11_ERROR_HINT = "잠시 후 다시 시도해 주세요"
F11_HOME_LINK_TEXT = "주제 목록으로"
F11_APP_NAME = "Study Log"
F11_BOOM_MESSAGE = "f11-secret-boom-message-7731"
F11_BOOM_PATH = "/f11-boom-page-zq"
F11_API_BOOM_PATH = "/api/f11-boom-zq"

F11_LOGIN_REQUIRED_BAD_PATHS = [
    "/subjects/abc",
    "/notes/abc",
    "/notes/abc/edit",
    "/subjects/abc/notes/new",
]
F11_UNKNOWN_PATHS = ["/없는주소", "/f11-unknown-path-zq", "/subjects", "/notes"]


def assert_f11_s6(response, status: int) -> None:
    """S6 오류 화면의 공통 모양: 상태 코드, HTML, 문구, 홈 링크, 보안 헤더, 스크립트 없음."""
    assert response.status_code == status, response.text[:300]
    assert response.headers["content-type"].startswith("text/html"), response.headers
    text = response.text
    assert F11_APP_NAME in text
    assert F11_HOME_LINK_TEXT in text
    assert 'href="/"' in text
    if status == 404:
        assert F11_NOT_FOUND_TITLE in text
        assert F11_NOT_FOUND_HINT in text
        assert F11_ERROR_TITLE not in text
    else:
        assert F11_ERROR_TITLE in text
        assert F11_ERROR_HINT in text
        assert F11_NOT_FOUND_TITLE not in text
    # JSON 원문이 아니다.
    assert not text.lstrip().startswith("{")
    assert '"error"' not in text
    assert '"code"' not in text
    # 스크립트 없이 동작한다.
    assert "<script" not in text.lower()
    # 보안 헤더
    assert response.headers.get("content-security-policy"), response.headers
    assert response.headers.get("x-content-type-options") == "nosniff"


def assert_f11_json_error(response, *, code: str | None = None) -> None:
    assert response.headers["content-type"].startswith("application/json"), (
        response.status_code,
        response.headers,
        response.text[:200],
    )
    body = response.json()
    assert "error" in body, body
    assert "code" in body["error"], body
    if code is not None:
        assert body["error"]["code"] == code, body


@pytest.fixture
def f11_boom_client(tmp_path: Path):
    """처리되지 않은 예외를 던지는 GET 라우트를 더한 로그인 상태의 클라이언트."""
    app = create_app(make_settings(database_url="sqlite:///" + str(tmp_path / "x.db")))

    @app.get(F11_BOOM_PATH)
    def boom_page():
        raise RuntimeError(F11_BOOM_MESSAGE)

    @app.get(F11_API_BOOM_PATH)
    def boom_api():
        raise RuntimeError(F11_BOOM_MESSAGE)

    with TestClient(app, raise_server_exceptions=False) as c:
        login = c.post("/api/login", json={"password": TEST_PASSWORD})
        assert login.status_code == 204, login.text
        yield c


# --- 404: 로그인한 상태 ---------------------------------------------------------


@pytest.mark.parametrize("path", F11_LOGIN_REQUIRED_BAD_PATHS, ids=lambda p: p)
def test_f11_logged_in_bad_id_on_screen_path_is_404_s6(auth_client: TestClient, path: str):
    response = auth_client.get(path, follow_redirects=False)
    assert_f11_s6(response, 404)


@pytest.mark.parametrize("path", F11_UNKNOWN_PATHS, ids=lambda p: p)
def test_f11_logged_in_unknown_path_is_404_s6(auth_client: TestClient, path: str):
    response = auth_client.get(path, follow_redirects=False)
    assert_f11_s6(response, 404)


def test_f11_s6_404_body_does_not_echo_the_requested_path(auth_client: TestClient):
    for path in ("/없는주소", "/f11-unknown-path-zq"):
        response = auth_client.get(path)
        assert_f11_s6(response, 404)
        assert path.lstrip("/") not in response.text
    # 잘못된 id 값도 본문에 되돌려 주지 않는다.
    response = auth_client.get("/subjects/f11zqid")
    assert_f11_s6(response, 404)
    assert "f11zqid" not in response.text


@pytest.mark.parametrize(
    "path",
    ["/subjects/-1", "/subjects/1.5", "/subjects/1/notes/new/extra", "/notes/1/delete"],
    ids=lambda p: p,
)
def test_f11_logged_in_malformed_screen_paths_are_404_s6(auth_client: TestClient, path: str):
    response = auth_client.get(path, follow_redirects=False)
    assert_f11_s6(response, 404)


# --- 404: 미로그인 ---------------------------------------------------------------


@pytest.mark.parametrize("path", F11_UNKNOWN_PATHS, ids=lambda p: p)
def test_f11_logged_out_unknown_path_is_404_s6(client: TestClient, path: str):
    response = client.get(path, follow_redirects=False)
    assert_f11_s6(response, 404)


@pytest.mark.parametrize("path", F11_LOGIN_REQUIRED_BAD_PATHS, ids=lambda p: p)
def test_f11_logged_out_login_required_screen_redirects_to_login(
    client: TestClient, path: str
):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302, response.text[:300]
    assert response.headers["location"].startswith("/login")


@pytest.mark.parametrize(
    "path",
    ["/", "/subjects/1", "/subjects/99999", "/subjects/1/notes/new", "/notes/1", "/notes/1/edit"],
    ids=lambda p: p,
)
def test_f11_logged_out_valid_screen_paths_still_redirect_to_login(
    client: TestClient, path: str
):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302, response.text[:300]
    assert response.headers["location"].startswith("/login")


def test_f11_login_page_still_shown_when_logged_out(client: TestClient):
    response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert F11_NOT_FOUND_TITLE not in response.text


# --- 숫자 id인데 자원이 없는 화면은 200 그대로 ------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/subjects/99999", "/notes/99999", "/notes/99999/edit", "/subjects/99999/notes/new"],
    ids=lambda p: p,
)
def test_f11_logged_in_numeric_id_without_resource_is_200_html_as_before(
    auth_client: TestClient, path: str
):
    response = auth_client.get(path, follow_redirects=False)
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"].startswith("text/html")
    assert F11_NOT_FOUND_TITLE not in response.text
    assert F11_NOT_FOUND_HINT not in response.text


def test_f11_existing_screens_are_200_html_when_logged_in(auth_client: TestClient):
    sid = make_subject(auth_client, "S6 회귀 주제")
    note = post_note(auth_client, sid, "본문").json()
    for path in (
        "/",
        f"/subjects/{sid}",
        f"/subjects/{sid}/notes/new",
        f"/notes/{note['id']}",
        f"/notes/{note['id']}/edit",
    ):
        response = auth_client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path
        assert F11_NOT_FOUND_TITLE not in response.text, path


# --- /api/, /static/, GET이 아닌 요청은 JSON 그대로 ---------------------------------


def test_f11_unknown_api_path_stays_json_not_found_when_logged_in(auth_client: TestClient):
    for path in ("/api/없는주소", "/api/f11-unknown-zq", "/api/subjects/abc/nothing"):
        response = auth_client.get(path)
        assert response.status_code == 404, path
        assert_f11_json_error(response, code="not_found")
        assert F11_NOT_FOUND_TITLE not in response.text


def test_f11_unknown_static_path_stays_json_not_found(auth_client: TestClient):
    for path in ("/static/없는파일", "/static/f11-missing-zq.js"):
        response = auth_client.get(path)
        assert response.status_code == 404, path
        assert_f11_json_error(response, code="not_found")
        assert F11_NOT_FOUND_TITLE not in response.text


def test_f11_unknown_static_path_stays_json_when_logged_out(client: TestClient):
    response = client.get("/static/없는파일")
    assert response.status_code == 404
    assert_f11_json_error(response, code="not_found")


def test_f11_non_get_requests_to_unknown_or_screen_paths_stay_json(auth_client: TestClient):
    responses = [
        auth_client.post("/없는주소", json={}),
        auth_client.post("/", json={}),
        auth_client.post("/subjects/abc", json={}),
        auth_client.delete("/없는주소"),
        auth_client.patch("/없는주소", json={}),
    ]
    for response in responses:
        assert response.status_code in (404, 405), response.status_code
        assert_f11_json_error(response)
        assert F11_NOT_FOUND_TITLE not in response.text
        assert F11_HOME_LINK_TEXT not in response.text


def test_f11_non_get_unknown_path_is_json_not_found(auth_client: TestClient):
    response = auth_client.post("/없는주소", json={})
    assert response.status_code == 404
    assert_f11_json_error(response, code="not_found")


def test_f11_api_errors_keep_their_json_shape(auth_client: TestClient):
    missing = auth_client.get("/api/subjects/99999")
    assert missing.status_code == 404
    assert_f11_json_error(missing, code="not_found")
    invalid = auth_client.post("/api/subjects", json={"name": ""})
    assert invalid.status_code == 422
    assert_f11_json_error(invalid, code="validation_error")


def test_f11_api_unauthorized_stays_401_json_when_logged_out(client: TestClient):
    response = client.get("/api/subjects")
    assert response.status_code == 401
    assert_f11_json_error(response, code="unauthorized")


# --- 처리되지 않은 예외 -----------------------------------------------------------


def test_f11_unhandled_exception_on_html_path_is_500_s6(f11_boom_client: TestClient):
    response = f11_boom_client.get(F11_BOOM_PATH)
    assert_f11_s6(response, 500)


def test_f11_500_s6_hides_exception_message_and_path(f11_boom_client: TestClient):
    response = f11_boom_client.get(F11_BOOM_PATH)
    assert_f11_s6(response, 500)
    text = response.text
    assert F11_BOOM_MESSAGE not in text
    assert "RuntimeError" not in text
    assert F11_BOOM_PATH.lstrip("/") not in text
    assert "traceback" not in text.lower()
    assert ".py" not in text
    assert "File \"" not in text


def test_f11_500_s6_is_returned_even_when_logged_out(tmp_path: Path):
    app = create_app(make_settings(database_url="sqlite:///" + str(tmp_path / "x.db")))

    @app.get(F11_BOOM_PATH)
    def boom_page():
        raise RuntimeError(F11_BOOM_MESSAGE)

    with TestClient(app, raise_server_exceptions=False) as anonymous:
        response = anonymous.get(F11_BOOM_PATH)
    assert_f11_s6(response, 500)
    assert F11_BOOM_MESSAGE not in response.text


def test_f11_unhandled_exception_on_api_path_stays_500_json_internal_error(
    f11_boom_client: TestClient,
):
    response = f11_boom_client.get(F11_API_BOOM_PATH)
    assert response.status_code == 500
    assert_f11_json_error(response, code="internal_error")
    assert F11_BOOM_MESSAGE not in response.text
    assert F11_ERROR_TITLE not in response.text


def test_f11_app_keeps_serving_after_a_500(f11_boom_client: TestClient):
    assert f11_boom_client.get(F11_BOOM_PATH).status_code == 500
    assert f11_boom_client.get("/").status_code == 200
    assert f11_boom_client.get("/api/subjects").status_code == 200


# --- S6 공통 모양(404와 500 모두) --------------------------------------------------


def test_f11_s6_has_security_headers_and_no_script_for_404_and_500(
    f11_boom_client: TestClient,
):
    not_found = f11_boom_client.get("/f11-unknown-path-zq")
    server_error = f11_boom_client.get(F11_BOOM_PATH)
    for response, status in ((not_found, 404), (server_error, 500)):
        assert response.status_code == status
        assert response.headers.get("content-security-policy")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert "<script" not in response.text.lower()
        assert response.headers["content-type"].startswith("text/html")


def test_f11_s6_404_and_500_differ_only_in_wording(f11_boom_client: TestClient):
    not_found = f11_boom_client.get("/f11-unknown-path-zq")
    server_error = f11_boom_client.get(F11_BOOM_PATH)
    assert F11_NOT_FOUND_TITLE in not_found.text and F11_NOT_FOUND_TITLE not in server_error.text
    assert F11_ERROR_TITLE in server_error.text and F11_ERROR_TITLE not in not_found.text
    for response in (not_found, server_error):
        assert F11_APP_NAME in response.text
        assert 'href="/"' in response.text
        assert F11_HOME_LINK_TEXT in response.text


# ===========================================================================
# F8: 작성 내용 보호 (서버가 정하는 부분: 로그인 화면의 next 검사와 만료 안내)
#
# 초안 보관·복원, 이탈 확인, 401 때 초안 저장과 이동은 브라우저 동작이라
# 메인 세션이 실제 브라우저로 확인한다. 여기서는 GET /login이 내려주는 값만 확인한다.
#
# 해석(F8)
# - GET /login은 `<section id="s1">`의 `data-next`에 검사를 통과한 경로를 넣고,
#   통과하지 못했거나 `next`가 없으면 빈 값을 넣는다.
# - `#login-expired`는 `expired=1`일 때만 `hidden` 없이 내려간다.
# - 허용 경로는 쿼리나 조각이 없는 정확한 경로뿐이다.
# ===========================================================================

from html.parser import HTMLParser  # noqa: E402

F8_EXPIRED_MESSAGE = "로그인이 만료되었습니다. 다시 로그인하세요"

F8_ALLOWED_NEXT = [
    "/",
    "/subjects/12",
    "/subjects/12/notes/new",
    "/notes/12",
    "/notes/12/edit",
]

F8_REJECTED_NEXT = [
    "https://evil.example",
    "http://evil.example/notes/1",
    "//evil.example",
    "///evil.example",
    "\\\\evil.example",
    "\\evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "/login",
    "/api/subjects",
    "/static/app.css",
    "/subjects",
    "/subjects/abc",
    "/subjects/0",
    "/subjects/-1",
    "/subjects/1.5",
    "/notes/1/edit/x",
    "/notes/1/",
    "/subjects/1?x=1",
    "/subjects/1#a",
    " /subjects/1",
    "/subjects/1\n",
    "/" + "a" * 5000,
    "/notes/" + "9" * 30,
    "/notes/１",
    "",
    "%2F%2Fevil.example",
]


class _LoginPageParser(HTMLParser):
    """s1 섹션과 #login-expired 요소의 속성, #login-expired 안의 글자를 모은다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.s1_attrs: dict[str, str | None] | None = None
        self.expired_attrs: dict[str, str | None] | None = None
        self.expired_text = ""
        self._expired_tag: str | None = None
        self._expired_depth = 0

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if attr_map.get("id") == "s1" and self.s1_attrs is None:
            self.s1_attrs = attr_map
        if self._expired_tag is not None:
            if tag == self._expired_tag:
                self._expired_depth += 1
        elif attr_map.get("id") == "login-expired" and self.expired_attrs is None:
            self.expired_attrs = attr_map
            self._expired_tag = tag
            self._expired_depth = 1

    def handle_endtag(self, tag):
        if self._expired_tag is not None and tag == self._expired_tag:
            self._expired_depth -= 1
            if self._expired_depth == 0:
                self._expired_tag = None

    def handle_data(self, data):
        if self._expired_tag is not None:
            self.expired_text += data


def f8_parse_login(response) -> _LoginPageParser:
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"].startswith("text/html")
    parser = _LoginPageParser()
    parser.feed(response.text)
    parser.close()
    return parser


def f8_data_next(response) -> str:
    """로그인 화면 HTML에서 s1 섹션의 data-next 값을 엔티티를 푼 채로 꺼낸다."""
    parser = f8_parse_login(response)
    assert parser.s1_attrs is not None, '<section id="s1">가 있어야 한다'
    assert "data-next" in parser.s1_attrs, "s1 섹션에 data-next 속성이 있어야 한다"
    value = parser.s1_attrs["data-next"]
    return "" if value is None else value


def f8_open_login(client: TestClient, **params):
    return client.get("/login", params=params, follow_redirects=False)


# --- next 허용 경로 ----------------------------------------------------------------


@pytest.mark.parametrize("path", F8_ALLOWED_NEXT, ids=lambda p: p)
def test_f8_login_data_next_keeps_allowed_path(client: TestClient, path: str):
    response = f8_open_login(client, next=path)
    assert f8_data_next(response) == path


@pytest.mark.parametrize("path", F8_ALLOWED_NEXT, ids=lambda p: p)
def test_f8_login_data_next_keeps_allowed_path_together_with_expired(
    client: TestClient, path: str
):
    response = f8_open_login(client, expired="1", next=path)
    assert f8_data_next(response) == path


def test_f8_login_data_next_decodes_percent_encoded_allowed_path(client: TestClient):
    # 서버가 쿼리를 디코드한 결과 기준으로 검사한다.
    response = client.get("/login?next=%2Fsubjects%2F12%2Fnotes%2Fnew", follow_redirects=False)
    assert f8_data_next(response) == "/subjects/12/notes/new"


# --- next 거부 경로 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    F8_REJECTED_NEXT,
    ids=lambda p: repr(p) if len(p) < 60 else f"long-{len(p)}-chars",
)
def test_f8_login_data_next_is_empty_for_rejected_path(client: TestClient, path: str):
    response = f8_open_login(client, next=path)
    assert f8_data_next(response) == ""


@pytest.mark.parametrize(
    "path",
    ["https://evil.example", "//evil.example", "/api/subjects", "/subjects/abc"],
    ids=lambda p: p,
)
def test_f8_login_data_next_is_empty_for_rejected_path_with_expired(
    client: TestClient, path: str
):
    response = f8_open_login(client, expired="1", next=path)
    assert f8_data_next(response) == ""


def test_f8_login_data_next_is_empty_for_percent_encoded_open_redirect(client: TestClient):
    # 주소에 %2F%2F로 보낸 값은 서버가 `//evil.example`로 디코드하므로 거부된다.
    response = client.get("/login?next=%2F%2Fevil.example", follow_redirects=False)
    assert f8_data_next(response) == ""
    response = client.get("/login?next=https%3A%2F%2Fevil.example", follow_redirects=False)
    assert f8_data_next(response) == ""


def test_f8_login_data_next_is_empty_for_encoded_query_after_decoding(client: TestClient):
    # 디코드하면 `/subjects/1?x=1`이므로 쿼리가 있어 거부된다.
    response = client.get("/login?next=%2Fsubjects%2F1%3Fx%3D1", follow_redirects=False)
    assert f8_data_next(response) == ""
    # 디코드하면 `/subjects/1#a`
    response = client.get("/login?next=%2Fsubjects%2F1%23a", follow_redirects=False)
    assert f8_data_next(response) == ""


def test_f8_login_data_next_is_empty_when_next_is_missing(client: TestClient):
    for params in ({}, {"expired": "1"}):
        response = f8_open_login(client, **params)
        assert f8_data_next(response) == "", params


def test_f8_login_with_repeated_next_never_uses_an_unsafe_value(client: TestClient):
    response = client.get(
        "/login?next=/notes/1&next=//evil.example", follow_redirects=False
    )
    assert f8_data_next(response) in ("", "/notes/1")
    response = client.get(
        "/login?next=//evil.example&next=/notes/1", follow_redirects=False
    )
    assert f8_data_next(response) in ("", "/notes/1")


# --- next 값이 HTML로 새지 않는다 -------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        '"><script>alert(1)</script>',
        "'><script>alert(1)</script>",
        '/notes/1"><script>alert(1)</script>',
        '" onmouseover="alert(1)',
        "</section><script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
    ],
    ids=["dq-script", "sq-script", "valid-prefix-script", "attr-injection", "close-section", "img"],
)
def test_f8_login_next_markup_does_not_leak_into_html(client: TestClient, payload: str):
    for extra in ({}, {"expired": "1"}):
        response = f8_open_login(client, next=payload, **extra)
        assert response.status_code == 200
        lowered = response.text.lower()
        assert "<script>alert" not in lowered
        assert "<img src=x" not in lowered
        assert 'onmouseover="alert' not in lowered
        # 거부되었으므로 data-next는 비어 있고 페이지 구조도 그대로다.
        assert f8_data_next(response) == ""


# --- 세션 만료 안내 -----------------------------------------------------------------


def test_f8_login_expired_notice_is_visible_when_expired_is_1(client: TestClient):
    parser = f8_parse_login(f8_open_login(client, expired="1"))
    assert parser.expired_attrs is not None, "#login-expired 요소가 있어야 한다"
    assert "hidden" not in parser.expired_attrs
    assert F8_EXPIRED_MESSAGE in " ".join(parser.expired_text.split())


def test_f8_login_expired_notice_is_visible_with_expired_and_next(client: TestClient):
    parser = f8_parse_login(f8_open_login(client, expired="1", next="/notes/12/edit"))
    assert parser.expired_attrs is not None
    assert "hidden" not in parser.expired_attrs
    assert F8_EXPIRED_MESSAGE in " ".join(parser.expired_text.split())


def test_f8_login_expired_notice_is_hidden_when_expired_is_missing(client: TestClient):
    parser = f8_parse_login(client.get("/login", follow_redirects=False))
    assert parser.expired_attrs is not None, "#login-expired 요소는 항상 있어야 한다"
    assert "hidden" in parser.expired_attrs


def test_f8_login_expired_notice_is_hidden_with_next_only(client: TestClient):
    parser = f8_parse_login(f8_open_login(client, next="/notes/12"))
    assert parser.expired_attrs is not None
    assert "hidden" in parser.expired_attrs


@pytest.mark.parametrize(
    "value", ["0", "true", "True", "yes", "2", "01", "", "1abc"], ids=lambda v: repr(v)
)
def test_f8_login_expired_notice_is_hidden_for_values_other_than_1(
    client: TestClient, value: str
):
    parser = f8_parse_login(f8_open_login(client, expired=value))
    assert parser.expired_attrs is not None
    assert "hidden" in parser.expired_attrs, value


# --- 로그인 상태와 미로그인 이동 ---------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"expired": "1", "next": "/notes/1"},
        {"next": "/notes/1"},
        {"expired": "1"},
        {"next": "//evil.example"},
    ],
    ids=["expired+next", "next", "expired", "bad-next"],
)
def test_f8_login_page_when_logged_in_redirects_to_root(auth_client: TestClient, params: dict):
    response = auth_client.get("/login", params=params, follow_redirects=False)
    assert response.status_code == 302, response.text[:300]
    assert response.headers["location"] == "/"


@pytest.mark.parametrize(
    "path",
    ["/", "/subjects/1", "/subjects/1/notes/new", "/notes/1", "/notes/1/edit"],
    ids=lambda p: p,
)
def test_f8_logged_out_screen_redirects_to_plain_login_without_query(
    client: TestClient, path: str
):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302, response.text[:300]
    # 서버가 expired나 next 쿼리를 붙이지 않는다(붙이는 것은 브라우저 JS의 일이다).
    assert response.headers["location"] == "/login"


def test_f8_logged_out_note_edit_redirects_to_plain_login(client: TestClient):
    response = client.get("/notes/1/edit", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_f8_login_page_is_html_200_when_logged_out(client: TestClient):
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Study Log" in response.text
