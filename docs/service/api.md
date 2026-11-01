# API

## 공통 규칙
- 모든 `/api/*` 요청·응답은 JSON(`Content-Type: application/json`)이다. F6 내보내기만 `text/markdown`.
- 로그인·로그아웃을 제외한 모든 API는 `session` 쿠키가 유효해야 한다. 없거나 만료면 `401 {"error":{"code":"unauthorized","message":"로그인이 필요합니다"}}`.
- 오류 응답은 모두 `{"error":{"code": string, "message": string, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}` 모양이다. `fields`는 422에서만, `retry_after`는 429와 503 `storage_busy`에서만, `current`는 409에서만 붙는다. 검증 실패는 422, 없는 자원은 404.
- DB를 쓰는 모든 API는 저장소 장애에서 503을 돌려준다(아래 "F10 저장소 장애"). 표의 오류 응답 칸에는 따로 적지 않는다.
- 본문이 있는 POST·PATCH는 `Content-Type: application/json`이어야 한다. 아니면 `415 {"error":{"code":"unsupported_media_type","message":"JSON 형식으로 보내야 합니다"}}`.
- 날짜는 `YYYY-MM-DD`, 시각은 ISO 8601 UTC(`2026-10-31T11:20:00Z`). 만들 수 없는 날짜(`0000-01-01` 등)는 422다.
- 목록은 `{"items": [...], "total": n, "page": p, "limit": l}` 모양이고 `page`는 1부터, `limit` 기본 20·최대 100.
- 깨진 JSON과 객체가 아닌 본문은 422 `fields.request`로 돌려준다.
- 처리되지 않은 예외는 500 `internal_error`로 돌려준다.
- 본문이 1MiB를 넘으면 413 `payload_too_large`다. `Content-Length`가 올바르지 않으면 400 `bad_request`다.
- 모든 응답에 보안 헤더가 붙는다: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options`, `Referrer-Policy`.
- `/api` 응답에는 `Cache-Control: no-store`가 붙는다.
- `PUBLIC_DEPLOY=true`이면 모든 응답에 HSTS(`Strict-Transport-Security`)가 붙는다.
- `/openapi.json`, `/docs`, `/redoc`은 없다.
- 로그인이 필요한 API는 로그인 전이면 401, 로그인 후면 422 `fields.request`다. `/api/login`은 422 `fields.request`다.

## 입력 문자 규칙
- name, title, memo: 줄바꿈과 제어 문자를 쓸 수 없다. 거부하면 422 `fields`에 `줄바꿈이나 제어 문자를 쓸 수 없습니다`.
- 태그: 앞뒤 공백(탭, 줄바꿈 포함)을 먼저 지운 뒤 검사한다. 쉼표와 제어 문자를 쓸 수 없다. 거부하면 422 `태그에 쉼표나 제어 문자를 쓸 수 없습니다`.
- background, body: 줄바꿈과 탭을 뺀 제어 문자(NUL 포함)를 쓸 수 없다. 거부하면 422 `쓸 수 없는 제어 문자가 있습니다`.
- F4의 `q`에 NUL이 있으면 422 `검색어에 쓸 수 없는 문자가 있습니다`다. `tag` 쿼리에 제어 문자가 있으면 422 `태그 조건에 쓸 수 없는 문자가 있습니다`다.
- `password`는 이 규칙에서 뺀다(아래 F5 참고).

## 화면(HTML) 주소
| 주소 | 화면 | 미로그인 시 |
|---|---|---|
| GET /login, GET /login?expired=1&next=<경로> | S1 | 그대로 표시(로그인 상태면 /로 이동) |
| GET / | S2 | 302 → /login |
| GET /subjects/{id} | S3 | 302 → /login |
| GET /subjects/{id}/notes/new | S4(작성) | 302 → /login |
| GET /notes/{id} | S5 | 302 → /login |
| GET /notes/{id}/edit | S4(수정) | 302 → /login |

HTML 페이지는 뼈대만 내려주고, 데이터는 페이지의 JS가 위 API로 가져온다.

`next`로 돌아갈 수 있는 경로는 위 표의 로그인 필요 화면뿐이다: `/`, `/subjects/{숫자}`, `/subjects/{숫자}/notes/new`, `/notes/{숫자}`, `/notes/{숫자}/edit`. 그 밖의 값(다른 사이트 주소, `//`나 `\`로 시작하는 값, 형식이 다른 경로)은 무시하고 `/`로 간다.

S6(F11): 경로가 `/api/`나 `/static/`으로 시작하지 않는 GET 요청에서 404나 처리되지 않은 예외가 나면 같은 상태 코드로 S6 HTML을 돌려준다.
- 로그인한 상태로 연 `/subjects/abc`, `/notes/abc/edit`, 없는 주소는 404 S6이다.
- 미로그인이면 로그인 필요 화면은 지금처럼 302 → /login이다. 표에 없는 주소는 미로그인이어도 404 S6이다.
- `/subjects/99999`처럼 숫자 id가 없는 자원이면 지금처럼 200 페이지를 내려주고 JS가 "찾을 수 없습니다"를 보인다.
- `/api/*`와 `/static/*`의 오류, GET이 아닌 요청의 오류는 지금처럼 JSON이다.

## F5 로그인·로그아웃

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F5 | POST | /api/login | `{password}` | 204 + `Set-Cookie: session=...; HttpOnly; SameSite=Lax; Max-Age=2592000` | 401 invalid_password / 429 too_many_attempts / 500 server_misconfigured |
| F5 | POST | /api/logout | 없음 | 204 + 쿠키 삭제 | 403 forbidden |

### F5 POST /api/login
요청
```json
{ "password": "correct horse battery staple" }
```
성공: 204, 본문 없음, `Set-Cookie: session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000` (`PUBLIC_DEPLOY=true`면 항상 `Secure` 추가, 꺼져 있으면 HTTPS 요청에만 추가)

오류 401
```json
{ "error": { "code": "invalid_password", "message": "비밀번호가 올바르지 않습니다" } }
```
오류 429 (5회 연속 실패 후 60초)
```json
{ "error": { "code": "too_many_attempts", "message": "잠시 후 다시 시도하세요", "retry_after": 60 } }
```
오류 500 (`APP_PASSWORD`나 `SECRET_KEY`가 비어 있을 때. 어떤 비밀번호를 보내도 같고, 실패 횟수에 세지 않는다)
```json
{ "error": { "code": "server_misconfigured", "message": "서버 설정이 올바르지 않습니다" } }
```

`password`가 1024자를 넘으면 비교 없이 401 `invalid_password`를 내고, 실패 횟수에 들어간다.

### F5 POST /api/logout
성공: 204, `Set-Cookie: session=; Max-Age=0`

오류 403: `Sec-Fetch-Site: cross-site` 요청이면 쿠키를 지우지 않고 거부한다.
```json
{"error":{"code":"forbidden","message":"다른 사이트에서 보낸 요청입니다"}}
```

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
| F3, F9 | PATCH | /api/notes/{id} | `{kind?, title?, body?, tags?, is_open?, expected_updated_at?}` | 200 Note | 404 / 409 conflict / 422 |
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

### F9 PATCH /api/notes/{id} 수정 충돌
요청 예
```json
{ "title": "csv 저장", "body": "수정한 본문", "expected_updated_at": "2026-10-31T11:25:00Z" }
```
- `expected_updated_at`은 선택이다. 보내지 않으면 충돌을 검사하지 않고 F3 그대로 동작한다.
- 보내면 저장된 `updated_at`을 응답과 같은 표기(초 단위 `YYYY-MM-DDTHH:MM:SSZ`)로 바꿔 글자 그대로 비교한다. 다르면 아무것도 저장하지 않고 409다.
- 같은 1초 안에 일어난 두 저장은 구분하지 못한다. 사용자 1명이라 받아들인다.
- `expected_updated_at`은 저장 필드가 아니다. 이것만 보내면 일치할 때 아무것도 바꾸지 않고 200 Note이며 `updated_at`도 그대로다.
- 형식이 틀리면 422 `fields.expected_updated_at: "수정 시각 형식이 올바르지 않습니다"`.
- 검사 순서는 입력값(422), 없는 노트(404), 충돌(409)이다.

오류 409
```json
{
  "error": {
    "code": "conflict",
    "message": "다른 곳에서 먼저 수정된 노트입니다",
    "current": {
      "id": 7,
      "subject_id": 1,
      "kind": "remember",
      "title": "csv 저장 시 인덱스 제외",
      "body": "다른 기기에서 고친 본문",
      "tags": ["pandas", "csv"],
      "is_open": false,
      "created_at": "2026-10-31T11:25:00Z",
      "updated_at": "2026-10-31T12:02:00Z"
    }
  }
}
```

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

`q`는 앞뒤 공백을 지운 뒤 200자 이내, `tag`는 최대 20개이고 각 1~30자다. 벗어나면 422다. `q`에 NUL 문자가 있으면 422 `검색어에 쓸 수 없는 문자가 있습니다`다.

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

## F8 작성 내용 보호

### F8 초안 저장
서버 API는 없다. S4가 브라우저 `localStorage`에 쓰고 읽는 약속이다. 키와 필드는 설계 문서 4절 "Draft"를 따른다. 키는 작성이면 `draft:new:{subject_id}`, 수정이면 `draft:note:{note_id}`다.

키 `draft:note:7`의 값 예(수정 중)
```json
{
  "kind": "remember",
  "title": "csv 저장 시 인덱스 제외",
  "tags_text": "pandas, csv",
  "is_open": false,
  "body": "쓰고 있던 본문",
  "base_updated_at": "2026-10-31T11:25:00Z",
  "saved_at": "2026-10-31T12:00:05Z"
}
```
키 `draft:new:1`의 값 예(작성 중): 같은 모양이고 `base_updated_at`만 null이다.

| 때 | 동작 |
|---|---|
| 입력이 멈추고 1초 뒤, 저장 버튼, 페이지를 떠날 때, 401을 받았을 때 | 초안을 쓴다 |
| S4를 열 때 | 초안을 읽어 안내 줄을 보일지 정한다 |
| 저장 성공, "버리기", 취소 확인, "서버 버전 불러오기" | 그 키를 지운다 |
| 로그아웃 성공 | `draft:`로 시작하는 키를 모두 지운다 |

## F10 저장소 장애

DB를 쓰는 모든 `/api/*`에 공통이다. SQLAlchemy가 던진 DB 오류만 503으로 바꾸고, 그 밖의 예외는 500 `internal_error`다. 오류 내용(SQL, 경로, 예외 문구)은 응답에 넣지 않고 서버 로그에만 남긴다.

| 기능 ID | 상황 | 상태 | code | message | 비고 |
|---|---|---|---|---|---|
| F10 | DB가 잠겨 5초 안에 쓰지 못함 | 503 | `storage_busy` | 저장소가 잠시 바쁩니다. 잠시 후 다시 시도하세요 | `retry_after: 5`, `Retry-After: 5` 헤더 |
| F10 | 읽기 전용, 용량 부족, 테이블 없음, 파일 손상 등 그 밖의 DB 오류 | 503 | `storage_unavailable` | 저장소에 문제가 있어 처리하지 못했습니다 | 재시도 안내 없음 |

오류 503 `storage_busy`
```json
{ "error": { "code": "storage_busy", "message": "저장소가 잠시 바쁩니다. 잠시 후 다시 시도하세요", "retry_after": 5 } }
```
오류 503 `storage_unavailable`
```json
{ "error": { "code": "storage_unavailable", "message": "저장소에 문제가 있어 처리하지 못했습니다" } }
```
화면은 자동으로 다시 보내지 않는다. 서버 문구를 보이고, 입력을 유지하고, 버튼을 다시 켠다.

## F11 화면 공통 오류 처리

공통 `api` 함수와 로그인·내보내기의 직접 요청에 같은 규칙을 쓴다. 새 API는 없다.

| 기능 ID | 상황 | 결과 | 문구 |
|---|---|---|---|
| F11 | 15초 안에 응답이 없음, GET | 요청을 끊고 실패로 돌려준다 | 서버 응답이 없습니다. 잠시 후 다시 시도하세요 |
| F11 | 15초 안에 응답이 없음, GET 외 | 요청을 끊고 실패로 돌려준다 | 응답을 받지 못했습니다. 저장되었는지 확인한 뒤 다시 시도하세요 |
| F11 | 연결 실패 | 기존과 같다 | 서버에 연결할 수 없습니다 |
| F11 | 401 | 초안을 저장하고 `/login?expired=1&next=<현재 경로>`로 이동한다 | S1 세션 만료 안내 |
| F11 | 2xx인데(204 제외) JSON이 아님 | 성공이 아니라 실패로 돌려준다 | 서버 응답을 해석할 수 없습니다 |
| F11 | 로그아웃 요청 실패 | S2에 머문다. 초안은 지우지 않는다 | 로그아웃하지 못했습니다 |

- 실패하면 어느 화면이든 입력을 유지하고 버튼을 다시 켠다.
- 로그인 잠금(429)의 문구는 `retry_after`의 초를 보여 준다.
