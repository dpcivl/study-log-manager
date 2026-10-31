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
