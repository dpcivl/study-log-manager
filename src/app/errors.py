"""오류 응답 모양. design.md 5절 공통 규칙:
{"error": {"code": str, "message": str, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}
"""

from starlette.responses import JSONResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    **extra,
) -> JSONResponse:
    """오류 본문을 만드는 공용 함수. extra 중 None인 값은 넣지 않는다."""
    error = {"code": code, "message": message}
    error.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
        retry_after: int | None = None,
        current: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.retry_after = retry_after
        self.current = current  # 409 conflict에서 서버에 있는 지금의 노트(F9)

    def body(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.fields is not None:
            error["fields"] = self.fields
        if self.retry_after is not None:
            error["retry_after"] = self.retry_after
        if self.current is not None:
            error["current"] = self.current
        return {"error": error}


class NotImplementedAPIError(APIError):
    """뼈대 단계의 자리표시. 구현되면 지운다."""

    def __init__(self) -> None:
        super().__init__(501, "not_implemented", "아직 구현되지 않음")


# ---- 422 fields 문구 ----
# 필드 이름 → 사람이 읽는 문구. 오류 종류와 상관없이 그 필드의 제한값을 알려 준다.
# 각 기능이 자기 필드의 문구를 여기에 더한다(design.md 4·5절 제한값).
FIELD_MESSAGES: dict[str, str] = {
    # F1 Subject
    "name": "이름은 1~100자여야 합니다",
    "background": "배경은 5000자 이하여야 합니다",
    "started_on": "시작일은 YYYY-MM-DD 형식의 날짜여야 합니다",
    "target_date": "목표일은 YYYY-MM-DD 형식의 날짜여야 합니다",
    # F2 StudySession
    "studied_on": "날짜는 YYYY-MM-DD 형식이어야 합니다",
    "minutes": "1~1440 사이여야 합니다",
    "memo": "메모는 500자 이하여야 합니다",
    # F3 Note
    "kind": "remember, debug, review 중 하나여야 합니다",
    "title": "제목은 1~200자여야 합니다",
    "body": "본문은 50,000자 이내여야 합니다",
    "tags": "태그는 최대 20개, 각 1~30자",
    # F9 노트 수정 충돌
    "expected_updated_at": "수정 시각 형식이 올바르지 않습니다",
    # 목록 쿼리(F2부터 쓴다). F4의 kind는 위 F3 문구를 같이 쓴다.
    "open": "open은 true 또는 false여야 합니다",
    "page": "1 이상의 정수여야 합니다",
    "limit": "1~100 사이의 정수여야 합니다",
}

# 제어 문자(와 태그의 쉼표)로 거부된 값은 길이 안내 대신 이유를 말한다. 검증기가 이 문구로
# ValueError를 던지면 validation_fields가 그대로 필드 문구로 쓴다.
CONTROL_ONE_LINE_MESSAGE = "줄바꿈이나 제어 문자를 쓸 수 없습니다"
CONTROL_MULTI_LINE_MESSAGE = "쓸 수 없는 제어 문자가 있습니다"
TAG_CHARS_MESSAGE = "태그에 쉼표나 제어 문자를 쓸 수 없습니다"
_REASON_MESSAGES = frozenset(
    {CONTROL_ONE_LINE_MESSAGE, CONTROL_MULTI_LINE_MESSAGE, TAG_CHARS_MESSAGE}
)
_VALUE_ERROR_PREFIX = "Value error, "

# 경로의 id 이름 → 404 문구. 정수가 아닌 id나 범위 밖 id는 "없는 자원"으로 본다.
NOT_FOUND_MESSAGES: dict[str, str] = {
    "subject_id": "주제를 찾을 수 없습니다",
    "session_id": "기록을 찾을 수 없습니다",
    "note_id": "노트를 찾을 수 없습니다",
}


CONFLICT_MESSAGE = "다른 곳에서 먼저 수정된 노트입니다"


def conflict(current: dict) -> APIError:
    """409 conflict. current는 서버에 있는 지금의 노트(F9)."""
    return APIError(409, "conflict", CONFLICT_MESSAGE, current=current)


def not_found(param: str) -> APIError:
    """경로 id 이름(NOT_FOUND_MESSAGES의 키)에 맞는 404 오류."""
    return APIError(404, "not_found", NOT_FOUND_MESSAGES[param])


# 요청 본문 전체가 잘못됐을 때(깨진 JSON, 객체가 아님)의 fields 키. 어떤 필드 이름과도 겹치지 않게
# 한다(Note의 body 필드와 구분).
REQUEST_FIELD = "request"
BODY_INVALID_MESSAGE = "요청 본문이 올바른 JSON 객체가 아닙니다"
REQUIRED_MESSAGE = "필수 항목입니다"
INVALID_MESSAGE = "올바른 값이 아닙니다"


def validation_fields(errors: list[dict]) -> dict[str, str]:
    """Pydantic 오류 목록을 {필드명: 문구}로 바꾼다. 필드마다 첫 오류만 쓴다."""
    fields: dict[str, str] = {}
    for err in errors:
        loc = list(err.get("loc", ()))
        # 첫 원소는 오류 위치(body·query·path)다. 그것만 떼고, 필드 이름 "body"는 남긴다.
        if loc and loc[0] in ("body", "query", "path"):
            loc = loc[1:]
        if not loc or not isinstance(loc[0], str):
            # 깨진 JSON, 객체가 아닌 본문 등 필드를 특정할 수 없는 경우
            key, default = REQUEST_FIELD, BODY_INVALID_MESSAGE
        else:
            key = loc[0]
            default = REQUIRED_MESSAGE if err.get("type") == "missing" else INVALID_MESSAGE
        reason = str(err.get("msg", "")).removeprefix(_VALUE_ERROR_PREFIX)
        if err.get("type") == "value_error" and reason in _REASON_MESSAGES:
            fields.setdefault(key, reason)
        else:
            fields.setdefault(key, FIELD_MESSAGES.get(key, default))
    return fields
