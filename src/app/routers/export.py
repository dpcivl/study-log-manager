"""F6 GET /api/subjects/{id}/export"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.errors import NotImplementedAPIError

router = APIRouter(prefix="/api", tags=["F6"], dependencies=[Depends(require_session)])


@router.get("/subjects/{subject_id}/export", response_class=PlainTextResponse)
def export_subject(subject_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    # 200 text/markdown; charset=utf-8
    # Content-Disposition: attachment; filename*=UTF-8''<name>.md / 404
    raise NotImplementedAPIError()
