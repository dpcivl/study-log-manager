# 구현 진행 기록

## 기능 현황
| ID | 기능 | 상태 | 테스트 루프 | 리뷰 라운드 |
| --- | --- | --- | --- | --- |
| F5 | 비밀번호 로그인 (뼈대 + F5) | 대기 | 0 | 0 |
| F1 | 학습 주제 관리 | 대기 | 0 | 0 |
| F2 | 공부 시간 기록 | 대기 | 0 | 0 |
| F3 | 노트 작성·보기·수정·삭제 | 대기 | 0 | 0 |
| F4 | 노트 검색·필터 | 대기 | 0 | 0 |
| F6 | 마크다운 내보내기 (선택) | 대기 | 0 | 0 |
| SEED | 초기 데이터 시드 스크립트 scripts/seed_bigdata.py | 대기 | 0 | 0 |

상태: 대기 / 진행 / 완료 / critical

## 해석 기록
- (없음)

## 실행 기록
- 2026-10-31 뼈대: Python 3.12 venv, FastAPI 앱, 모델·스키마·모든 API 스텁(501 not_implemented), 템플릿·정적 파일 자리, tests/conftest.py 픽스처. 서버·pytest(0개)·ruff 실행 확인. `src/app/errors.py`를 추가했다(오류 응답 모양을 라우터가 공유하기 위해). vendor JS(marked, highlight.js, DOMPurify)는 F3에서 받는다.
