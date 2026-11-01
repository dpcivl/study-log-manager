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

해석
- 본문 최대 길이 50,000자는 그대로이고 50,001자는 전처럼 422(fields.body)다.
"""

from fastapi.testclient import TestClient

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
