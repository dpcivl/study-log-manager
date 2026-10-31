"""F6 GET /api/subjects/{id}/export"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import require_session
from app.db import get_db
from app.deps import IdPath, get_subject_or_404
from app.exporter import content_disposition, export_filename, export_subject_markdown

router = APIRouter(prefix="/api", tags=["F6"], dependencies=[Depends(require_session)])


@router.get("/subjects/{subject_id}/export", response_class=Response)
def export_subject(subject_id: IdPath, db: Session = Depends(get_db)) -> Response:
    # 200 text/markdown; charset=utf-8
    # Content-Disposition: attachment; filename*=UTF-8''<name>.md / 404
    subject = get_subject_or_404(db, subject_id)
    return Response(
        content=export_subject_markdown(db, subject),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition(export_filename(subject.name))},
    )
