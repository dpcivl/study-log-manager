"""요청 본문 크기 상한(SEC-2). 순수 ASGI 미들웨어라 본문을 읽기 전에 거른다.

POST·PATCH 요청에 적용하고, 로그인 여부와 상관없이 본문이 MAX_BODY_BYTES를 넘으면 413으로
끝낸다.
- Content-Length가 있으면 본문을 읽기 전에 판단한다. 형식이 틀리면 400, 상한을 넘으면 413이며
  뒤쪽(415 검사, 라우터, 핸들러)에는 닿지 않는다. 자릿수가 아주 많은 값도 413이다.
- Content-Length 없이(또는 거짓으로) 온 본문은 앱이 본문을 읽는 경로에서 실제로 읽은 바이트를
  센다. 따라서 본문을 읽지 않는 /api/logout은 204로 끝나고, JSON이 아닌 본문은 415 검사가
  먼저 응답할 수 있다.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response

MAX_BODY_BYTES = 1024 * 1024  # 1MiB = 1048576바이트
LIMITED_METHODS = frozenset({"POST", "PATCH"})
_MAX_DIGITS = 19  # 앞의 0을 뺀 자릿수가 이보다 많으면 상한을 넘는 값으로 본다


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    # 본문을 다 읽지 않았을 수 있으므로 연결을 재사용하지 않는다.
    return error_response(status_code, code, message, headers={"connection": "close"})


def _too_large() -> JSONResponse:
    return _error(413, "payload_too_large", "요청 본문이 너무 큽니다")


def _bad_content_length() -> JSONResponse:
    return _error(400, "bad_request", "Content-Length가 올바르지 않습니다")


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in LIMITED_METHODS:
            await self.app(scope, receive, send)
            return

        declared = [v for k, v in scope["headers"] if k == b"content-length"]
        if declared:
            raw = declared[0].strip()
            if not (raw.isascii() and raw.isdigit()) or any(v.strip() != raw for v in declared):
                await _bad_content_length()(scope, receive, send)
                return
            # 숫자 형식을 먼저 확인했으므로, 자릿수가 많으면 변환하지 않고 413으로 처리한다.
            # 앞의 0을 지우고 변환한다(0이 아주 많아도 변환 한도에 걸리지 않게). 모두 0이면 0이다.
            digits = raw.lstrip(b"0")
            if len(digits) > _MAX_DIGITS or (int(digits) if digits else 0) > self.max_bytes:
                await _too_large()(scope, receive, send)
                return

        # Content-Length가 없거나 거짓이어도 실제로 읽은 바이트를 센다.
        # 넘는 순간 아직 응답이 시작되지 않았다면 413을 직접 보내고, 앱에는 연결이 끊긴 것으로
        # 알린다. (예외를 던지면 FastAPI가 본문 읽기 오류를 400으로 바꿔 버린다.)
        # 앱 응답을 버리는 것은 413을 보낸 경우뿐이다. 이미 응답이 시작됐으면 앱 응답을 그대로 둔다.
        received = 0
        exceeded = False
        sent_413 = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded, sent_413
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    if not response_started:
                        # 보내는 동안 앱 응답이 끼어들지 않도록 먼저 표시한다.
                        sent_413 = True
                        await _too_large()(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if sent_413:  # 413을 보낸 뒤 앱이 보내려는 응답은 버린다.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
