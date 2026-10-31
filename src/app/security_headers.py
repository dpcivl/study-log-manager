"""보안 응답 헤더(SEC-6). 순수 ASGI 미들웨어라 가장 바깥에 두면 본문 상한의 413·400을 포함해
모든 응답에 붙는다. 500 처리기의 응답은 이 미들웨어를 거치지 않으므로
security_headers로 직접 붙인다.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 화면은 같은 출처의 스크립트·스타일만 쓴다(인라인 없음). 이미지는 data:와 https만 더 허용한다.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
HSTS = "max-age=31536000"


def security_headers(path: str, public_deploy: bool) -> dict[str, str]:
    """이 응답에 붙일 보안 헤더. path는 ASGI scope의 path다."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    }
    if path.startswith("/api"):
        headers["Cache-Control"] = "no-store"
    if public_deploy:
        headers["Strict-Transport-Security"] = HSTS
    return headers


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, public_deploy: bool = False) -> None:
        self.app = app
        self.public_deploy = public_deploy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        extra = security_headers(scope["path"], self.public_deploy)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in extra.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
