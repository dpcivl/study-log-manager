"""라우터가 같이 쓰는 FastAPI 의존성·경로 매개변수."""

from typing import Annotated

from fastapi import Path

# 경로의 id. SQLite 정수 범위 안으로 제한한다. 정수가 아니거나 범위 밖이면 없는 자원(404)으로
# 처리된다(main.py의 검증 오류 핸들러가 매개변수 이름으로 errors.NOT_FOUND_MESSAGES를 찾는다).
# Path(...) 인스턴스를 직접 공유하면 FastAPI가 매개변수 이름을 섞으므로 Annotated 별칭으로 쓴다.
IdPath = Annotated[int, Path(ge=1, le=2**63 - 1)]
