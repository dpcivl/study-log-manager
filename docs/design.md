# 설계 문서: Study Log Manager

## 1. 개요
- 목적: 마크다운 파일 하나에 섞여 있던 학습 기록(공부 시간, 기억할 것, 디버깅, 후기)을 주제별로 구조화해 저장하고, PC와 폰 어디서나 적고 다시 찾아볼 수 있게 한다.
- 대상 사용자: 본인 1명. 첫 주제는 "빅데이터분석기사 실기"이고, 이후 다른 자격증·공부 주제를 같은 구조로 추가한다.
- 한 줄 소개: 비밀번호 하나로 보호되는 개인용 학습 노트 웹앱. 주제마다 공부 시간을 쌓고, 마크다운 노트를 유형·태그·미해결 여부로 분류해 검색한다.

## 2. 기능 목록
| ID | 기능 | 우선순위(필수/선택) | 완료 기준 |
|---|---|---|---|
| F1 | 학습 주제 관리: 주제를 만들고(이름, 배경, 시작일, 목표일) 목록과 상세를 보고 수정한다 | 필수 | 주제 목록에 생성 최신순으로 모든 주제가 이름·시작일·누적 공부 시간(h)·노트 수·미해결 노트 수와 함께 표시된다. 이름이 비어 있으면 422로 거부되고 화면에 오류 문구가 보인다. 수정 후 새로고침해도 바뀐 값이 유지된다 |
| F2 | 공부 시간 기록: 주제별로 날짜와 분 단위 시간을 기록하고 고치거나 지우며, 누적·최근 7일 합계를 본다 | 필수 | 기록 추가 직후 목록 맨 위(날짜 최신순)에 나타나고 누적 합계가 그만큼 늘어난다. 최근 7일 합계는 오늘 포함 7일(KST) 안의 기록만 더한다. 수정해 저장하면 바뀐 값이 목록과 합계에 즉시 반영된다. 삭제하면 목록과 합계에서 즉시 빠진다. 분이 1 미만이거나 1440 초과면 422 |
| F3 | 노트 작성·보기·수정·삭제: 유형(기억할 것/디버깅/후기) 하나를 골라 제목·마크다운 본문·태그·미해결 여부를 저장한다 | 필수 | 저장한 노트를 S5에서 열면 마크다운이 렌더되고 ```python 코드 블록이 구문 강조된다. 디버깅 유형을 고르고 본문이 비어 있으면 "## 문제상황 / ## 원인 / ## 해결" 템플릿이 본문에 채워진다. 제목이 비어 있으면 422. 삭제 확인 후 노트 목록에서 사라지고 GET /api/notes/{id}는 404 |
| F4 | 노트 검색·필터: 유형, 태그, 미해결 여부, 검색어로 주제 안의 노트를 거른다 | 필수 | 필터 조건을 하나 이상 걸면 조건을 모두(AND) 만족하는 노트만 수정 최신순으로 20개씩 표시되고, 21개 이상이면 "더 보기"로 다음 20개가 붙는다. 검색어는 제목과 본문에 대소문자 구분 없이 부분 일치한다. 결과가 없으면 "조건에 맞는 노트가 없습니다" 문구가 보인다 |
| F5 | 비밀번호 로그인: 환경 변수에 둔 비밀번호 하나로 로그인하면 세션 쿠키가 발급되고, 로그아웃하면 사라진다 | 필수 | 로그인하지 않은 상태에서 /api/* 호출은 401, 화면 주소는 /login으로 이동한다. 올바른 비밀번호로 로그인하면 S2로 이동하고 브라우저를 닫았다 열어도 30일 안에는 유지된다. 틀린 비밀번호 5회 연속이면 60초 동안 429로 거부된다 |
| F6 | 마크다운 내보내기: 주제 하나를 지금 쓰던 마크다운 형식(# 베이스 / # 기간 / # 공부 기록 / # 기억할 것 / # 디버깅 / # 후기)으로 내려받는다 | 선택 | 내보내기 버튼을 누르면 `<주제이름>.md` 파일이 내려받히고, 공부 기록은 "- 10월 26일: 1h" 형식으로, 노트는 유형별 섹션 아래 "## 제목" + 본문으로 들어 있다 |

## 3. 화면 구성

### S1 로그인
- 목적: 비밀번호를 받아 세션을 만든다.
- 주요 요소:
  - 앱 이름 "Study Log"
  - 비밀번호 입력(type=password, autofocus)
  - "로그인" 버튼
  - 오류 문구 영역(틀렸을 때 "비밀번호가 올바르지 않습니다", 429일 때 "잠시 후 다시 시도하세요 (60초)")
- 연결된 기능: F5
- 이동: 성공 → S2

### S2 주제 목록
- 목적: 모든 학습 주제를 한눈에 보고 새 주제를 만든다.
- 주요 요소:
  - 상단 바: 앱 이름, "로그아웃" 버튼
  - "새 주제" 버튼 → 아래에 인라인 폼이 펼쳐짐: 이름(필수), 시작일(date, 기본 오늘), 목표일(date, 선택), 배경(textarea, 선택) / "만들기" "취소"
  - 주제 카드 목록(생성 최신순). 카드마다: 이름, 시작일, 목표일까지 D-day(목표일 없으면 생략), 누적 공부 시간 "12.5h", 노트 수, 미해결 노트 수(0이면 숨김)
  - 주제가 하나도 없으면 "첫 학습 주제를 만들어 보세요" 빈 상태 문구
- 연결된 기능: F1, F5
- 이동: 카드 클릭 → S3 / 로그아웃 → S1

### S3 주제 상세
- 목적: 한 주제의 공부 시간과 노트를 관리하는 메인 작업 화면.
- 주요 요소:
  - 상단 바: "← 주제 목록" 링크, 주제 이름, "편집" 버튼(이름·시작일·목표일·배경을 인라인 폼으로 수정, "저장" "취소"), "내보내기" 버튼(F6)
  - 요약 줄: 시작일 ~ 목표일, D-day, 누적 "12.5h", 최근 7일 "5h", 공부한 날 수
  - 배경 텍스트(여러 줄, 비어 있으면 숨김)
  - **공부 시간** 섹션
    - 빠른 추가 폼: 날짜(date, 기본 오늘), 시간(number, 단위 분, step 15, 기본 60), 메모(선택), "추가" 버튼
    - 기록 목록(날짜 최신순): 날짜, "1h" 또는 "1.5h", 메모, "수정" 버튼, "삭제" 버튼. 20개씩 "더 보기"
    - "수정"을 누르면 그 행이 날짜·시간(분)·메모 입력과 "저장" "취소" 버튼으로 바뀐다. 저장에 실패하면 행 안에 오류 문구가 보인다
  - **노트** 섹션
    - "새 노트" 버튼 → S4
    - 필터 바: 유형 탭(전체 / 기억할 것 / 디버깅 / 후기), "미해결만" 체크박스, 태그 칩(이 주제의 태그 전부, 클릭하면 토글), 검색어 입력(입력 후 300ms 디바운스)
    - 노트 목록(수정 최신순): 제목, 유형 배지, 태그 칩, 미해결 배지, 수정일. 20개씩 "더 보기"
    - 결과 없음 문구
- 연결된 기능: F1, F2, F4, F6
- 이동: 노트 항목 클릭 → S5 / "새 노트" → S4 / "← 주제 목록" → S2

### S4 노트 편집 (작성·수정 공용)
- 목적: 노트 하나를 새로 쓰거나 고친다.
- 주요 요소:
  - 유형 선택(라디오: 기억할 것 / 디버깅 / 후기). 디버깅을 고르고 본문이 비어 있으면 템플릿 삽입
  - 제목 입력(필수, 200자 이내)
  - 태그 입력(쉼표로 구분, 예: "pandas, csv")
  - "미해결" 체크박스(답을 아직 못 채운 질문일 때)
  - 본문 textarea(마크다운, 50,000자 이내) / "미리보기" 토글(같은 자리에 렌더 결과 표시)
  - "저장" "취소" 버튼
  - 오류 문구 영역
- 연결된 기능: F3
- 이동: 저장 → S5 / 취소 → 작성이면 S3, 수정이면 S5

### S5 노트 보기
- 목적: 노트 하나를 읽는다.
- 주요 요소:
  - "← 주제" 링크
  - 제목, 유형 배지, 태그 칩, 미해결 배지, 작성일·수정일
  - 렌더된 본문(제목·목록·인라인 코드·코드 블록 구문 강조)
  - "수정" 버튼 → S4, "삭제" 버튼(confirm 창 "이 노트를 삭제할까요?")
- 연결된 기능: F3
- 이동: 수정 → S4 / 삭제 → S3 / "← 주제" → S3

## 4. 데이터 모델

### Subject (학습 주제)
| 필드 | 타입 | 설명 |
|---|---|---|
| id | integer | PK, 자동 증가 |
| name | string(1..100) | 주제 이름. 필수 |
| background | string(0..5000) | 배경·베이스 메모. 기본 "" |
| started_on | date | 시작일. 필수 |
| target_date | date \| null | 목표일(시험일). 선택 |
| created_at | datetime(UTC) | 생성 시각 |
| updated_at | datetime(UTC) | 수정 시각 |

응답에만 붙는 계산 필드: `total_minutes`(integer), `last7_minutes`(integer, 오늘 포함 7일 KST), `days_studied`(integer, 기록이 있는 날짜 수), `note_count`(integer), `open_note_count`(integer).

### StudySession (공부 시간 기록)
| 필드 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| subject_id | integer | FK → Subject.id, 주제 삭제 시 함께 삭제 |
| studied_on | date | 공부한 날짜. 필수 |
| minutes | integer(1..1440) | 공부한 분. 필수 |
| memo | string(0..500) | 메모. 기본 "" |
| created_at | datetime(UTC) | 생성 시각 |

### Note (노트)
| 필드 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| subject_id | integer | FK → Subject.id, 주제 삭제 시 함께 삭제 |
| kind | enum "remember" \| "debug" \| "review" | 기억할 것 / 디버깅 / 후기 |
| title | string(1..200) | 제목. 필수 |
| body | string(0..50000) | 마크다운 본문. 기본 "" |
| tags | string[] (각 1..30자, 최대 20개, 소문자·공백 trim 저장) | SQLite에는 JSON 배열 문자열로 저장 |
| is_open | boolean | 미해결 여부. 기본 false |
| created_at | datetime(UTC) | 생성 시각 |
| updated_at | datetime(UTC) | 수정 시각 |

### 인증 상태
- 사용자 테이블은 없다. 비밀번호는 환경 변수 `APP_PASSWORD`에 둔다.
- 세션은 `SECRET_KEY`로 서명한 쿠키 `session`(값: 발급 시각이 든 서명 토큰, 만료 30일)이다. 서버 저장은 없다.
- 로그인 실패 횟수는 서버 메모리에 IP별로 둔다(5회 실패 → 60초 잠금). 재시작하면 초기화된다.

### 공통 요청·응답 필드 (저장하지 않음)
| 필드 | 타입 | 설명 |
|---|---|---|
| password | string | 로그인 요청에만 쓴다. 저장하지 않는다 |
| error | object | 오류 응답의 최상위 필드 |
| error.code | string | 오류 코드. 예: `validation_error`, `not_found`, `unsupported_media_type` |
| error.message | string | 화면에 보여 줄 문구 |
| error.fields | object(필드명: string) \| 없음 | 422에서 필드별 오류 문구 |
| error.retry_after | integer \| 없음 | 429에서 다시 시도할 수 있을 때까지 남은 초 |
| items | array | 목록 응답의 항목 |
| total | integer | 필터를 적용한 전체 개수 |
| page | integer | 현재 페이지. 1부터 |
| limit | integer | 페이지 크기. 기본 20, 최대 100 |

## 5. 인터페이스 약속

공통 규칙
- 모든 `/api/*` 요청·응답은 JSON(`Content-Type: application/json`)이다. F6 내보내기만 `text/markdown`.
- 로그인·로그아웃을 제외한 모든 API는 `session` 쿠키가 유효해야 한다. 없거나 만료면 `401 {"error":{"code":"unauthorized","message":"로그인이 필요합니다"}}`.
- 오류 응답은 모두 `{"error":{"code": string, "message": string, "fields"?: {필드명: 메시지}, "retry_after"?: 초}}` 모양이다. `fields`는 422에서만, `retry_after`는 429에서만 붙는다. 검증 실패는 422, 없는 자원은 404.
- 본문이 있는 POST·PATCH는 `Content-Type: application/json`이어야 한다. 아니면 `415 {"error":{"code":"unsupported_media_type","message":"JSON 형식으로 보내야 합니다"}}`.
- 날짜는 `YYYY-MM-DD`, 시각은 ISO 8601 UTC(`2026-10-31T11:20:00Z`).
- 목록은 `{"items": [...], "total": n, "page": p, "limit": l}` 모양이고 `page`는 1부터, `limit` 기본 20·최대 100.

| 기능 ID | 메서드 | 주소 | 요청 | 성공 응답 | 오류 응답 |
|---|---|---|---|---|---|
| F5 | POST | /api/login | `{password}` | 204 + `Set-Cookie: session=...; HttpOnly; SameSite=Lax; Max-Age=2592000` | 401 invalid_password / 429 too_many_attempts |
| F5 | POST | /api/logout | 없음 | 204 + 쿠키 삭제 | 없음 |
| F1 | GET | /api/subjects | 없음 | 200 `{items:[Subject+계산필드]}` 생성 최신순 | 401 |
| F1 | POST | /api/subjects | `{name, background?, started_on, target_date?}` | 201 Subject+계산필드 | 422 validation_error |
| F1 | GET | /api/subjects/{id} | 없음 | 200 Subject+계산필드 | 404 not_found |
| F1 | PATCH | /api/subjects/{id} | `{name?, background?, started_on?, target_date?}` 보낸 필드만 수정 | 200 Subject+계산필드 | 404 / 422 |
| F2 | GET | /api/subjects/{id}/sessions?page&limit | 없음 | 200 목록(studied_on desc, 같은 날은 id desc) + `total_minutes` | 404 |
| F2 | POST | /api/subjects/{id}/sessions | `{studied_on, minutes, memo?}` | 201 StudySession | 404 / 422 |
| F2 | PATCH | /api/sessions/{id} | `{studied_on?, minutes?, memo?}` | 200 StudySession | 404 / 422 |
| F2 | DELETE | /api/sessions/{id} | 없음 | 204 | 404 |
| F3 | POST | /api/subjects/{id}/notes | `{kind, title, body?, tags?, is_open?}` | 201 Note | 404 / 422 |
| F3 | GET | /api/notes/{id} | 없음 | 200 Note | 404 |
| F3 | PATCH | /api/notes/{id} | `{kind?, title?, body?, tags?, is_open?}` | 200 Note | 404 / 422 |
| F3 | DELETE | /api/notes/{id} | 없음 | 204 | 404 |
| F4 | GET | /api/subjects/{id}/notes?kind&tag&q&open&page&limit | 쿼리만 | 200 목록(updated_at desc) + `tags`(이 주제의 태그 전부) | 404 / 422 |
| F6 | GET | /api/subjects/{id}/export | 없음 | 200 `text/markdown; charset=utf-8`, `Content-Disposition: attachment; filename*=UTF-8''<name>.md` | 404 |

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

### 화면(HTML) 주소
| 주소 | 화면 | 미로그인 시 |
|---|---|---|
| GET /login | S1 | 그대로 표시(로그인 상태면 /로 이동) |
| GET / | S2 | 302 → /login |
| GET /subjects/{id} | S3 | 302 → /login |
| GET /subjects/{id}/notes/new | S4(작성) | 302 → /login |
| GET /notes/{id} | S5 | 302 → /login |
| GET /notes/{id}/edit | S4(수정) | 302 → /login |

HTML 페이지는 뼈대만 내려주고, 데이터는 페이지의 JS가 위 API로 가져온다.

## 6. 기술 스택
- Python 3.12 + FastAPI: 사용자가 Python을 쓰고 있고, Pydantic으로 요청 검증과 422 응답 모양을 한 곳에서 맞출 수 있다.
- SQLAlchemy 2.x + SQLite(파일 `data/study.db`): 사용자 1명·소규모 데이터라 별도 DB 서버가 필요 없고 백업은 파일 복사로 끝난다. 테스트는 `:memory:` SQLite.
- pydantic-settings: `APP_PASSWORD`, `SECRET_KEY`, `DATABASE_URL`을 `.env`에서 읽는다.
- itsdangerous: 세션 쿠키 서명(서버 저장 없이 30일 만료 검증).
- Jinja2 + Vanilla JS(ES 모듈, 빌드 도구 없음): "가벼운 프론트" 요구. 페이지마다 JS 파일 하나가 fetch로 API를 부른다.
- marked 12.x + highlight.js 11.x + DOMPurify 3.x(`src/app/static/vendor/`에 파일로 포함): 마크다운 렌더·코드 하이라이트·XSS 정화. CDN 의존 없이 오프라인에서도 동작.
- pytest + httpx(FastAPI TestClient): API 계약 테스트. 각 테스트는 빈 `:memory:` DB로 시작한다.
- ruff: 린트·포맷.

폴더
```
src/app/
  main.py            FastAPI 앱 생성, 라우터 등록, 예외 핸들러(오류 응답 모양)
  settings.py        환경 변수
  db.py              엔진·세션·Base
  models.py          Subject, StudySession, Note
  schemas.py         Pydantic 요청·응답 모델
  auth.py            로그인 검사 의존성, 쿠키 발급, 실패 횟수 제한
  routers/           auth.py, subjects.py, sessions.py, notes.py, export.py, pages.py
  templates/         base.html, login.html, subjects.html, subject.html, note_edit.html, note.html
  static/            app.css, js/{login,subjects,subject,note_edit,note}.js, vendor/
tests/               test_auth.py, test_subjects.py, test_sessions.py, test_notes.py, test_export.py
docs/service/        사용자용 설명(실행·백업 방법)
data/                SQLite 파일(.gitignore)
```

실행 명령
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # APP_PASSWORD, SECRET_KEY 채우기
uvicorn app.main:app --app-dir src --reload --port 8000   # http://localhost:8000
pytest tests/
```

## 7. 구현 순서
1. 뼈대 + F5: 설정, DB, 오류 응답 핸들러, 로그인·로그아웃 API, 세션 의존성, S1, 미로그인 리다이렉트. 테스트: 401·로그인·415·429.
2. F1: Subject 모델·API, S2, S3의 헤더·요약·편집. 테스트: 생성·목록 정렬·422·PATCH.
3. F2: StudySession 모델·API, S3 공부 시간 섹션. 테스트: 합계·최근 7일·정렬·범위 검증·수정·삭제.
4. F3: Note 모델·API, S4(템플릿 삽입, 미리보기), S5(렌더·하이라이트·삭제). 테스트: 생성·수정·삭제·태그 정규화.
5. F4: 노트 목록 필터·페이지·태그 집계, S3 노트 섹션. 테스트: AND 필터·검색 대소문자·페이지 경계.
6. F6(선택): 내보내기 API와 버튼. 테스트: 섹션 순서·시간 표기.
7. 초기 데이터: 붙여 넣은 마크다운 노트를 넣는 시드 스크립트 `scripts/seed_bigdata.py`(주제 1개, 공부 기록 4건, 노트 6건).

## 8. 보안 고려 사항
- 인증: `APP_PASSWORD`와 입력을 `hmac.compare_digest`로 비교. 비밀번호·`SECRET_KEY`는 `.env`에만 두고 `.env`는 `.gitignore`에 넣는다. `.env.example`에는 빈 값만.
- 세션 쿠키: `HttpOnly`, `SameSite=Lax`, HTTPS 배포 시 `Secure`. 서명 토큰에 발급 시각을 넣어 30일 지나면 거부. `SECRET_KEY`를 바꾸면 모든 세션이 무효화된다(비밀번호 변경 시 함께 바꾸도록 docs/service에 적는다).
- 무차별 대입: IP별 5회 연속 실패 → 60초 429. 성공하면 카운터 초기화.
- CSRF: 본문이 있는 POST·PATCH는 JSON만 받고(아니면 415, 5절 공통 규칙), `SameSite=Lax` 쿠키와 함께 크로스 사이트 폼 전송을 막는다.
- 입력 검증: 모든 요청은 Pydantic 모델로 길이·범위·enum을 검사(4절의 제한값). 쿼리 `limit`은 100으로 상한. `page`·`limit`은 양의 정수.
- XSS: 마크다운 렌더 결과를 DOMPurify로 정화한 뒤 DOM에 넣는다. 사용자 텍스트를 `innerHTML`로 넣지 않고 `textContent`를 쓴다(본문 렌더 제외).
- SQL 인젝션: 모든 질의는 SQLAlchemy ORM·바인딩 파라미터. `q` 검색은 `LIKE` 바인딩 + `%`/`_` 이스케이프.
- 내보내기 파일명: 주제 이름에서 경로 문자(`/`, `\`, `..`)를 제거하고 `filename*=UTF-8''` 인코딩.
- 자원 접근: 사용자가 1명이므로 소유권 검사는 없지만, 모든 데이터 API가 로그인 의존성을 거치는지 테스트로 확인한다.
- 배포: 리버스 프록시(HTTPS) 뒤에서만 공개. `data/` 폴더는 주기적으로 복사해 백업.

## 9. 미결 사항
- 주제 삭제 기능을 넣을지(실수 삭제 위험 vs 정리 편의). 첫 버전은 없음.
- 배포 위치(개인 서버·Fly.io·Railway 등)와 HTTPS 방법. 결정되면 `Secure` 쿠키와 `docs/service`에 반영.
- 폰에서 코드가 든 긴 노트를 쓰는 편의(모노스페이스 입력, 탭 키). 첫 버전은 일반 textarea.
- 비밀번호 변경 절차: 현재는 `.env` 수정 + 재시작. 화면에서 바꾸는 기능은 보류.
- 공부 시간 입력 단위: API는 분, 화면은 분 입력(step 15). "1.5h"처럼 시간 단위 입력을 허용할지.
- 디버깅 노트를 구조화 필드(problem/cause/solution)로 바꿀지. 첫 버전은 본문 템플릿으로 대신한다.
