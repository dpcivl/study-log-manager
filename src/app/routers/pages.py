"""화면(HTML) 주소. design.md 5절 "화면(HTML) 주소" 표.
HTML 페이지는 뼈대만 내려주고, 데이터는 페이지의 JS가 API로 가져온다.
미로그인이면 S1 외 화면은 302 → /login (F5). 로그인 검사는 라우터 의존성 하나가 맡고,
경로 id 검증보다 먼저 돌므로 id가 정수가 아니어도 미로그인이면 302다.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import is_logged_in, require_page_login
from app.deps import IdPath

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 로그인 뒤 돌아갈 수 있는 화면(F8). 로그인이 필요한 화면의 정확한 경로뿐이다.
# [0-9]만 쓰고(\d는 다른 문자의 숫자도 받는다) fullmatch로 줄바꿈·쿼리·조각이 붙은 값을 거른다.
_NEXT_PATH = re.compile(r"/|/subjects/([1-9][0-9]*)(/notes/new)?|/notes/([1-9][0-9]*)(/edit)?")
_MAX_ID = 2**63 - 1  # IdPath와 같은 범위


def safe_next_path(value: str | None) -> str:
    """`next` 쿼리가 허용된 화면 경로면 그대로, 아니면 빈 문자열(S2로 간다)."""
    if not value or len(value) > 64:
        return ""
    match = _NEXT_PATH.fullmatch(value)
    if match is None:
        return ""
    for ident in (match.group(1), match.group(3)):
        if ident is not None and int(ident) > _MAX_ID:
            return ""
    return value


router = APIRouter(tags=["pages"], include_in_schema=False)
# 로그인이 필요한 화면. S1(/login)은 여기에 넣지 않는다.
protected = APIRouter(dependencies=[Depends(require_page_login)])


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    # S1. 로그인 상태면 /로 이동
    if is_logged_in(request):
        return RedirectResponse("/", status_code=302)
    # expired=1이면 세션 만료 안내를 보이고, 로그인 뒤 돌아갈 next는 허용된 경로만 내려준다(F8)
    context = {
        "expired": request.query_params.get("expired") == "1",
        "next_path": safe_next_path(request.query_params.get("next")),
    }
    return templates.TemplateResponse(request, "login.html", context)


@protected.get("/", response_class=HTMLResponse)
def subjects_page(request: Request) -> Response:
    # S2
    return templates.TemplateResponse(request, "subjects.html")


@protected.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_page(request: Request, subject_id: IdPath) -> Response:
    # S3
    return templates.TemplateResponse(request, "subject.html", {"subject_id": subject_id})


@protected.get("/subjects/{subject_id}/notes/new", response_class=HTMLResponse)
def note_new_page(request: Request, subject_id: IdPath) -> Response:
    # S4(작성)
    return templates.TemplateResponse(
        request, "note_edit.html", {"subject_id": subject_id, "note_id": None}
    )


@protected.get("/notes/{note_id}", response_class=HTMLResponse)
def note_page(request: Request, note_id: IdPath) -> Response:
    # S5
    return templates.TemplateResponse(request, "note.html", {"note_id": note_id})


@protected.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def note_edit_page(request: Request, note_id: IdPath) -> Response:
    # S4(수정)
    return templates.TemplateResponse(
        request, "note_edit.html", {"subject_id": None, "note_id": note_id}
    )


router.include_router(protected)
