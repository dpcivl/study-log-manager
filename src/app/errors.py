"""오류 응답 모양. design.md 5절 공통 규칙:
{"error": {"code": str, "message": str, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}
"""


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.retry_after = retry_after

    def body(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.fields is not None:
            error["fields"] = self.fields
        if self.retry_after is not None:
            error["retry_after"] = self.retry_after
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
}

# 경로의 id 이름 → 404 문구. 정수가 아닌 id나 범위 밖 id는 "없는 자원"으로 본다.
NOT_FOUND_MESSAGES: dict[str, str] = {
    "subject_id": "주제를 찾을 수 없습니다",
}

BODY_INVALID_MESSAGE = "요청 본문이 올바른 JSON 객체가 아닙니다"
REQUIRED_MESSAGE = "필수 항목입니다"
INVALID_MESSAGE = "올바른 값이 아닙니다"


def validation_fields(errors: list[dict]) -> dict[str, str]:
    """Pydantic 오류 목록을 {필드명: 문구}로 바꾼다. 필드마다 첫 오류만 쓴다."""
    fields: dict[str, str] = {}
    for err in errors:
        loc = [p for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        if not loc or not isinstance(loc[0], str):
            # 깨진 JSON, 객체가 아닌 본문 등 필드를 특정할 수 없는 경우
            key, default = "body", BODY_INVALID_MESSAGE
        else:
            key = loc[0]
            default = REQUIRED_MESSAGE if err.get("type") == "missing" else INVALID_MESSAGE
        fields.setdefault(key, FIELD_MESSAGES.get(key, default))
    return fields
