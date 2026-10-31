# API

## 공통 규칙
- 모든 `/api/*` 요청·응답은 JSON(`Content-Type: application/json`)이다. F6 내보내기만 `text/markdown`.
- 로그인·로그아웃을 제외한 모든 API는 `session` 쿠키가 유효해야 한다. 없거나 만료면 `401 {"error":{"code":"unauthorized","message":"로그인이 필요합니다"}}`.
- 오류 응답은 모두 `{"error":{"code": string, "message": string, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}` 모양이다. `fields`는 422에서만, `retry_after`는 429에서만 붙는다. 검증 실패는 422, 없는 자원은 404.
- 본문이 있는 POST·PATCH는 `Content-Type: application/json`이어야 한다. 아니면 `415 {"error":{"code":"unsupported_media_type","message":"JSON 형식으로 보내야 합니다"}}`.
- 날짜는 `YYYY-MM-DD`, 시각은 ISO 8601 UTC(`2026-10-31T11:20:00Z`).
- 목록은 `{"items": [...], "total": n, "page": p, "limit": l}` 모양이고 `page`는 1부터, `limit` 기본 20·최대 100.

## 화면(HTML) 주소
| 주소 | 화면 | 미로그인 시 |
|---|---|---|
| GET /login | S1 | 그대로 표시(로그인 상태면 /로 이동) |
| GET / | S2 | 302 → /login |
| GET /subjects/{id} | S3 | 302 → /login |
| GET /subjects/{id}/notes/new | S4(작성) | 302 → /login |
| GET /notes/{id} | S5 | 302 → /login |
| GET /notes/{id}/edit | S4(수정) | 302 → /login |

HTML 페이지는 뼈대만 내려주고, 데이터는 페이지의 JS가 위 API로 가져온다.

## F5 로그인·로그아웃

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F5 | POST | /api/login | `{password}` | 204 + `Set-Cookie: session=...; HttpOnly; SameSite=Lax; Max-Age=2592000` | 401 invalid_password / 429 too_many_attempts |
| F5 | POST | /api/logout | 없음 | 204 + 쿠키 삭제 | 없음 |

### F5 POST /api/login
요청
```json
{ "password": "correct horse battery staple" }
```
성공: 204, 본문 없음, `Set-Cookie: session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000` (HTTPS면 `Secure` 추가)

오류 401
```json
{ "error": { "code": "invalid_password", "message": "비밀번호가 올바르지 않습니다" } }
```
오류 429 (5회 연속 실패 후 60초)
```json
{ "error": { "code": "too_many_attempts", "message": "잠시 후 다시 시도하세요", "retry_after": 60 } }
```

### F5 POST /api/logout
성공: 204, `Set-Cookie: session=; Max-Age=0`
