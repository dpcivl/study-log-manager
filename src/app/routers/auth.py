"""F5 POST /api/login, POST /api/logout"""

from fastapi import APIRouter, Response, status

from app.errors import NotImplementedAPIError
from app.schemas import LoginRequest

router = APIRouter(prefix="/api", tags=["F5"])


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(payload: LoginRequest, response: Response) -> None:
    # 성공: 204 + Set-Cookie: session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000
    # 오류: 401 invalid_password / 429 too_many_attempts(retry_after)
    raise NotImplementedAPIError()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    # 성공: 204 + Set-Cookie: session=; Max-Age=0
    raise NotImplementedAPIError()
