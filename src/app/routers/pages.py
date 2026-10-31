"""화면(HTML) 주소. design.md 5절 "화면(HTML) 주소" 표.
HTML 페이지는 뼈대만 내려주고, 데이터는 페이지의 JS가 API로 가져온다.
미로그인 리다이렉트(302 → /login)는 F5에서 구현한다.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["pages"], include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    # S1. 로그인 상태면 /로 이동
    return templates.TemplateResponse(request, "login.html")


@router.get("/", response_class=HTMLResponse)
def subjects_page(request: Request) -> HTMLResponse:
    # S2
    return templates.TemplateResponse(request, "subjects.html")


@router.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_page(request: Request, subject_id: int) -> HTMLResponse:
    # S3
    return templates.TemplateResponse(request, "subject.html", {"subject_id": subject_id})


@router.get("/subjects/{subject_id}/notes/new", response_class=HTMLResponse)
def note_new_page(request: Request, subject_id: int) -> HTMLResponse:
    # S4(작성)
    return templates.TemplateResponse(
        request, "note_edit.html", {"subject_id": subject_id, "note_id": None}
    )


@router.get("/notes/{note_id}", response_class=HTMLResponse)
def note_page(request: Request, note_id: int) -> HTMLResponse:
    # S5
    return templates.TemplateResponse(request, "note.html", {"note_id": note_id})


@router.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def note_edit_page(request: Request, note_id: int) -> HTMLResponse:
    # S4(수정)
    return templates.TemplateResponse(
        request, "note_edit.html", {"subject_id": None, "note_id": note_id}
    )
