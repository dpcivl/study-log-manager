"""초기 데이터 시드 스크립트(scripts/seed_bigdata.py) 블랙박스 테스트.

완료 기준 (design.md 6절 이후 초기 데이터 항목)
- 붙여 넣은 마크다운 노트를 넣는 시드 스크립트 `scripts/seed_bigdata.py`
  (주제 1개, 공부 기록 4건, 노트 6건).

해석
- 스크립트는 프로젝트 폴더에서 `python scripts/seed_bigdata.py`로 실행하고 `DATABASE_URL`을 따른다.
  이 테스트는 항상 tmp_path 아래 임시 SQLite 파일을 주며 `data/study.db`는 건드리지 않는다.
- 결과는 기존 API(로그인한 TestClient)로 확인한다.
- 같은 이름의 주제가 이미 있으면 아무것도 바꾸지 않고 건너뛴다
  (중복 생성 없음, 기존 데이터 수정 없음).
- 사용자 글은 고치지 않고 그대로 넣는다. 후기는 "코딩팡 사용" 한 건에 모은다.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import TEST_PASSWORD, make_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = "scripts/seed_bigdata.py"

SUBJECT_NAME = "빅데이터분석기사 실기"
OPEN_NOTE_TITLE = "DataFrame의 isnull()과 isna()가 다른 이유?"
DEBUG_NOTE_TITLE = "FileNotFoundError: temp_csv"
REVIEW_NOTE_TITLE = "코딩팡 사용"
CSV_NOTE_TITLE = "csv 저장 시 인덱스 제외"
# design.md 5절 F3 POST 예시의 body
CSV_NOTE_BODY = (
    "인덱스를 제외하고 저장하려면 index=False\n\n```python\ndf.to_csv('cafe.csv', index=False)\n```"
)

HEADERS = ["# 베이스", "# 기간", "# 공부 기록", "# 기억할 것", "# 디버깅", "# 후기"]


def db_url_for(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/seed.db"


def run_seed(database_url: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    # .env가 없어도 설정 로딩이 실패하지 않도록 필수 값을 명시한다.
    env.setdefault("APP_PASSWORD", TEST_PASSWORD)
    env.setdefault("SECRET_KEY", "test-secret-key")
    return subprocess.run(
        [sys.executable, SEED_SCRIPT],
        env=env,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def open_client(database_url: str) -> TestClient:
    app = create_app(make_settings(database_url=database_url))
    client = TestClient(app)
    client.__enter__()
    response = client.post("/api/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204, response.text
    return client


@pytest.fixture
def seed_url(tmp_path: Path) -> str:
    return db_url_for(tmp_path)


@pytest.fixture
def seeded(seed_url: str):
    result = run_seed(seed_url)
    assert result.returncode == 0, result.stdout + result.stderr
    client = open_client(seed_url)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)


def get_notes(client: TestClient) -> dict:
    response = client.get("/api/subjects/1/notes", params={"limit": 100})
    assert response.status_code == 200, response.text
    return response.json()


def test_seed_exits_zero(seed_url: str):
    result = run_seed(seed_url)
    assert result.returncode == 0, result.stdout + result.stderr


def test_seed_creates_single_subject_with_expected_fields(seeded: TestClient):
    response = seeded.get("/api/subjects")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    subject = items[0]
    assert subject["id"] == 1
    assert subject["name"] == SUBJECT_NAME
    assert subject["started_on"] == "2026-10-26"
    assert subject["target_date"] is None
    assert "정보처리산업기사" in subject["background"]
    assert subject["total_minutes"] == 360
    assert subject["days_studied"] == 4
    assert subject["note_count"] == 6
    assert subject["open_note_count"] == 1


def test_seed_creates_four_study_sessions(seeded: TestClient):
    response = seeded.get("/api/subjects/1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["total_minutes"] == 360
    # 날짜 최신순 응답이므로 오름차순으로 뒤집어 확인한다.
    ascending = sorted(body["items"], key=lambda s: s["studied_on"])
    assert [s["studied_on"] for s in ascending] == [
        "2026-10-26",
        "2026-10-27",
        "2026-10-28",
        "2026-10-29",
    ]
    assert [s["minutes"] for s in ascending] == [60, 120, 60, 120]


def test_seed_creates_six_notes_with_expected_kinds_and_tags(seeded: TestClient):
    body = get_notes(seeded)
    assert body["total"] == 6
    assert len(body["items"]) == 6
    assert body["tags"] == ["csv", "datetime", "pandas"]

    kinds = [n["kind"] for n in body["items"]]
    assert kinds.count("remember") == 4
    assert kinds.count("debug") == 1
    assert kinds.count("review") == 1


def test_seed_has_exactly_one_open_note(seeded: TestClient):
    response = seeded.get("/api/subjects/1/notes", params={"open": "true", "limit": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == OPEN_NOTE_TITLE
    assert body["items"][0]["is_open"] is True

    all_open = [n for n in get_notes(seeded)["items"] if n["is_open"]]
    assert [n["title"] for n in all_open] == [OPEN_NOTE_TITLE]


def test_seed_csv_note_body_matches_design_example(seeded: TestClient):
    notes = [n for n in get_notes(seeded)["items"] if n["title"] == CSV_NOTE_TITLE]
    assert len(notes) == 1
    assert notes[0]["kind"] == "remember"
    assert notes[0]["body"] == CSV_NOTE_BODY


def test_seed_debug_note_has_template_sections(seeded: TestClient):
    debug_notes = [n for n in get_notes(seeded)["items"] if n["kind"] == "debug"]
    assert len(debug_notes) == 1
    note = debug_notes[0]
    assert note["title"] == DEBUG_NOTE_TITLE
    for expected in ("## 문제상황", "## 원인", "## 해결", "temp.csv"):
        assert expected in note["body"], expected


def test_seed_review_note_title(seeded: TestClient):
    review_notes = [n for n in get_notes(seeded)["items"] if n["kind"] == "review"]
    assert len(review_notes) == 1
    assert review_notes[0]["title"] == REVIEW_NOTE_TITLE


def test_seed_twice_does_not_duplicate(seed_url: str):
    first = run_seed(seed_url)
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_seed(seed_url)
    assert second.returncode == 0, second.stdout + second.stderr

    client = open_client(seed_url)
    try:
        items = client.get("/api/subjects").json()["items"]
        assert len(items) == 1
        assert items[0]["note_count"] == 6
        assert items[0]["days_studied"] == 4
        assert items[0]["total_minutes"] == 360

        sessions = client.get("/api/subjects/1/sessions", params={"limit": 100}).json()
        assert sessions["total"] == 4
        assert len(sessions["items"]) == 4

        notes = get_notes(client)
        assert notes["total"] == 6
        assert len(notes["items"]) == 6
    finally:
        client.__exit__(None, None, None)


def test_seed_skips_when_same_name_subject_exists_and_keeps_edits(seed_url: str):
    client = open_client(seed_url)
    try:
        created = client.post(
            "/api/subjects",
            json={"name": SUBJECT_NAME, "background": "원래 배경", "started_on": "2026-09-01"},
        )
        assert created.status_code == 201, created.text
        subject_id = created.json()["id"]
        patched = client.patch(
            f"/api/subjects/{subject_id}",
            json={
                "background": "내가 고친 배경",
                "started_on": "2026-09-15",
                "target_date": "2026-12-06",
            },
        )
        assert patched.status_code == 200, patched.text
    finally:
        client.__exit__(None, None, None)

    result = run_seed(seed_url)
    assert result.returncode == 0, result.stdout + result.stderr

    client = open_client(seed_url)
    try:
        items = client.get("/api/subjects").json()["items"]
        assert len(items) == 1
        subject = items[0]
        assert subject["name"] == SUBJECT_NAME
        assert subject["background"] == "내가 고친 배경"
        assert subject["started_on"] == "2026-09-15"
        assert subject["target_date"] == "2026-12-06"
        # 건너뛰었으므로 기록·노트도 새로 들어가지 않는다.
        assert subject["total_minutes"] == 0
        assert subject["note_count"] == 0
    finally:
        client.__exit__(None, None, None)


def test_seed_export_contains_seeded_content_in_order(seeded: TestClient):
    response = seeded.get("/api/subjects/1/export")
    assert response.status_code == 200
    text = response.text

    assert "- 10월 26일: 1h" in text
    assert "- 10월 27일: 2h" in text
    assert "## 코딩팡 사용" in text
    assert f"## {OPEN_NOTE_TITLE} (미해결)" in text

    positions = [text.index(header) for header in HEADERS]
    assert positions == sorted(positions)

    # 노트가 제 유형 섹션 아래에 있는지 확인한다.
    debug_at, review_at = positions[4], positions[5]
    assert positions[3] < text.index(f"## {CSV_NOTE_TITLE}") < debug_at
    assert positions[3] < text.index(f"## {OPEN_NOTE_TITLE} (미해결)") < debug_at
    assert debug_at < text.index(f"## {DEBUG_NOTE_TITLE}") < review_at
    assert review_at < text.index("## 코딩팡 사용")
