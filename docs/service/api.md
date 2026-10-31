# API

## 공통 규칙
- 모든 `/api/*` 요청·응답은 JSON(`Content-Type: application/json`)이다. F6 내보내기만 `text/markdown`.
- 로그인·로그아웃을 제외한 모든 API는 `session` 쿠키가 유효해야 한다. 없거나 만료면 `401 {"error":{"code":"unauthorized","message":"로그인이 필요합니다"}}`.
- 오류 응답은 모두 `{"error":{"code": string, "message": string, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}` 모양이다. `fields`는 422에서만, `retry_after`는 429에서만 붙는다. 검증 실패는 422, 없는 자원은 404.
- 본문이 있는 POST·PATCH는 `Content-Type: application/json`이어야 한다. 아니면 `415 {"error":{"code":"unsupported_media_type","message":"JSON 형식으로 보내야 합니다"}}`.
- 날짜는 `YYYY-MM-DD`, 시각은 ISO 8601 UTC(`2026-10-31T11:20:00Z`).
- 목록은 `{"items": [...], "total": n, "page": p, "limit": l}` 모양이고 `page`는 1부터, `limit` 기본 20·최대 100.
- 깨진 JSON과 객체가 아닌 본문은 422 `fields.request`로 돌려준다.
- 처리되지 않은 예외는 500 `internal_error`로 돌려준다.

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

## F1 학습 주제 관리

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F1 | GET | /api/subjects | 없음 | 200 `{items:[Subject+계산필드]}` 생성 최신순 | 401 |
| F1 | POST | /api/subjects | `{name, background?, started_on, target_date?}` | 201 Subject+계산필드 | 422 validation_error |
| F1 | GET | /api/subjects/{id} | 없음 | 200 Subject+계산필드 | 404 not_found |
| F1 | PATCH | /api/subjects/{id} | `{name?, background?, started_on?, target_date?}` 보낸 필드만 수정 | 200 Subject+계산필드 | 404 / 422 |

### F1 GET /api/subjects
```json
{
  "items": [
    {
      "id": 1,
      "name": "빅데이터분석기사 실기",
      "background": "임베디드 HW 개발 1년 / SW 개발 2년 5개월 / 정보처리산업기사 / AI 엔지니어 1개월째",
      "started_on": "2026-10-26",
      "target_date": null,
      "created_at": "2026-10-26T09:00:00Z",
      "updated_at": "2026-10-26T09:00:00Z",
      "total_minutes": 360,
      "last7_minutes": 360,
      "days_studied": 4,
      "note_count": 5,
      "open_note_count": 1
    }
  ]
}
```

### F1 POST /api/subjects
요청
```json
{ "name": "빅데이터분석기사 실기", "background": "임베디드 HW 1년...", "started_on": "2026-10-26", "target_date": null }
```
성공 201: 위 items 원소와 같은 모양(계산 필드는 모두 0)

오류 422
```json
{ "error": { "code": "validation_error", "message": "입력값을 확인하세요", "fields": { "name": "이름은 1~100자여야 합니다" } } }
```

### F1 GET /api/subjects/{id}, PATCH /api/subjects/{id}
PATCH 요청 예
```json
{ "target_date": "2026-12-06" }
```
성공 200: items 원소와 같은 모양. 오류 404
```json
{ "error": { "code": "not_found", "message": "주제를 찾을 수 없습니다" } }
```

## F2 공부 시간 기록

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F2 | GET | /api/subjects/{id}/sessions?page&limit | 없음 | 200 목록(studied_on desc, 같은 날은 id desc) + `total_minutes` | 404 |
| F2 | POST | /api/subjects/{id}/sessions | `{studied_on, minutes, memo?}` | 201 StudySession | 404 / 422 |
| F2 | PATCH | /api/sessions/{id} | `{studied_on?, minutes?, memo?}` | 200 StudySession | 404 / 422 |
| F2 | DELETE | /api/sessions/{id} | 없음 | 204 | 404 |

### F2 GET /api/subjects/{id}/sessions
```json
{
  "items": [
    { "id": 4, "subject_id": 1, "studied_on": "2026-10-29", "minutes": 120, "memo": "", "created_at": "2026-10-29T13:00:00Z" },
    { "id": 3, "subject_id": 1, "studied_on": "2026-10-28", "minutes": 60,  "memo": "시나공 ch3", "created_at": "2026-10-28T13:00:00Z" }
  ],
  "total": 4,
  "page": 1,
  "limit": 20,
  "total_minutes": 360
}
```

### F2 POST /api/subjects/{id}/sessions
요청
```json
{ "studied_on": "2026-10-31", "minutes": 90, "memo": "groupby 연습" }
```
성공 201
```json
{ "id": 5, "subject_id": 1, "studied_on": "2026-10-31", "minutes": 90, "memo": "groupby 연습", "created_at": "2026-10-31T11:20:00Z" }
```
오류 422
```json
{ "error": { "code": "validation_error", "message": "입력값을 확인하세요", "fields": { "minutes": "1~1440 사이여야 합니다" } } }
```

### F2 PATCH /api/sessions/{id}, DELETE /api/sessions/{id}
PATCH 요청 `{ "minutes": 60 }` → 200 StudySession. DELETE → 204. 없으면 404 not_found.

## F3 노트 작성·보기·수정·삭제

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F3 | POST | /api/subjects/{id}/notes | `{kind, title, body?, tags?, is_open?}` | 201 Note | 404 / 422 |
| F3 | GET | /api/notes/{id} | 없음 | 200 Note | 404 |
| F3 | PATCH | /api/notes/{id} | `{kind?, title?, body?, tags?, is_open?}` | 200 Note | 404 / 422 |
| F3 | DELETE | /api/notes/{id} | 없음 | 204 | 404 |

### F3 POST /api/subjects/{id}/notes
요청
```json
{
  "kind": "remember",
  "title": "csv 저장 시 인덱스 제외",
  "body": "인덱스를 제외하고 저장하려면 index=False\n\n```python\ndf.to_csv('cafe.csv', index=False)\n```",
  "tags": ["pandas", "csv"],
  "is_open": false
}
```
성공 201
```json
{
  "id": 7,
  "subject_id": 1,
  "kind": "remember",
  "title": "csv 저장 시 인덱스 제외",
  "body": "인덱스를 제외하고 저장하려면 index=False\n\n```python\ndf.to_csv('cafe.csv', index=False)\n```",
  "tags": ["pandas", "csv"],
  "is_open": false,
  "created_at": "2026-10-31T11:25:00Z",
  "updated_at": "2026-10-31T11:25:00Z"
}
```
오류 422 예: `fields.kind: "remember, debug, review 중 하나여야 합니다"`, `fields.title: "제목은 1~200자여야 합니다"`, `fields.tags: "태그는 최대 20개, 각 1~30자"`

### F3 GET /api/notes/{id}, PATCH /api/notes/{id}, DELETE /api/notes/{id}
PATCH 요청 예(미해결 질문에 답을 채움)
```json
{ "body": "isna()는 isnull()의 별칭이다. 동작이 같고 R 사용자를 위해 둘 다 둔 것", "is_open": false }
```
성공 200: Note 전체(updated_at 갱신). DELETE → 204. 없으면 404 `{"error":{"code":"not_found","message":"노트를 찾을 수 없습니다"}}`

## F4 노트 검색·필터

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F4 | GET | /api/subjects/{id}/notes?kind&tag&q&open&page&limit | 쿼리만 | 200 목록(updated_at desc) + `tags`(이 주제의 태그 전부) | 404 / 422 |

### F4 GET /api/subjects/{id}/notes
쿼리: `kind`(remember|debug|review), `tag`(정확히 일치, 여러 개면 `tag=a&tag=b` 모두 포함), `q`(제목·본문 부분 일치, 대소문자 무시), `open`(true면 is_open=true만), `page`, `limit`. 조건은 AND.

예: `GET /api/subjects/1/notes?kind=remember&open=true&q=isna`
```json
{
  "items": [
    {
      "id": 8,
      "subject_id": 1,
      "kind": "remember",
      "title": "DataFrame의 isnull()과 isna()가 다른 이유?",
      "body": "",
      "tags": ["pandas"],
      "is_open": true,
      "created_at": "2026-10-28T13:10:00Z",
      "updated_at": "2026-10-28T13:10:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20,
  "tags": ["csv", "pandas", "datetime"]
}
```
`tags`는 필터와 무관하게 이 주제 노트의 모든 태그(중복 제거, 가나다·알파벳순)이다. `kind`가 세 값 밖이면 422.

`q`는 앞뒤 공백을 지운 뒤 200자 이내, `tag`는 최대 20개이고 각 1~30자다. 벗어나면 422다.

## F6 마크다운 내보내기

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F6 | GET | /api/subjects/{id}/export | 없음 | 200 `text/markdown; charset=utf-8`, `Content-Disposition: attachment; filename*=UTF-8''<name>.md` | 404 |

### F6 GET /api/subjects/{id}/export
성공 200, `Content-Type: text/markdown; charset=utf-8`. 본문 예
```markdown
# 베이스
임베디드 HW 개발 1년 / SW 개발 2년 5개월 / 정보처리산업기사 / AI 엔지니어 1개월째

# 기간
- 시작: 2026-10-26
- 목표: (없음)

# 공부 기록
- 10월 26일: 1h
- 10월 27일: 2h

# 기억할 것
## csv 저장 시 인덱스 제외
태그: pandas, csv

인덱스를 제외하고 저장하려면 index=False

...

# 디버깅
## FileNotFoundError: temp_csv
...

# 후기
## 코딩팡 사용
...
```
공부 기록은 날짜 오름차순, 노트는 유형별 섹션 안에서 생성 오름차순. 미해결 노트는 제목 뒤에 ` (미해결)`을 붙인다.
