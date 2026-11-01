# 기능 현황
| ID | 기능 | 상태 | 완료일 | 남은 지적(minor·info) |
| --- | --- | --- | --- | --- |
| F1 | 학습 주제 관리 | 완료 | 2026-10-31 | minor 8건, info 8건. docs/impl-reports/F1.md 참고 |
| F2 | 공부 시간 기록 | 완료 | 2026-10-31 | minor 8건, info 8건. docs/impl-reports/F2.md 참고 |
| F3 | 노트 작성·보기·수정·삭제 | 완료 | 2026-10-31 | minor 10건, info 7건. docs/impl-reports/F3.md 참고 |
| F4 | 노트 검색·필터 | 완료 | 2026-10-31 | minor 7건, info 9건. docs/impl-reports/F4.md 참고 |
| F5 | 비밀번호 로그인 | 완료 | 2026-10-31 | minor 11건·info 11건. 대표: 프록시 뒤 IP·Secure 판정이 uvicorn 설정에 의존, 60초·30일 만료 테스트 없음, 동시 요청 테스트 단언이 `<= 5`. 전체: [F5 실행 보고서](../impl-reports/F5.md) |
| F6 | 마크다운 내보내기 | 완료 | 2026-10-31 | minor 6건, info 4건. docs/impl-reports/F6.md 참고 |
| SEED | 초기 데이터 시드 스크립트 | 완료 | 2026-10-31 | minor 4건, info 4건. docs/impl-reports/SEED.md 참고 |
| SEC | 보안 감사 결과 수정 | 완료 | 2026-11-01 | docs/impl-reports/SEC.md 참고 |
| F7 | 렌더 실패 복구 | 완료 | 2026-11-01 | minor 2건, info 4건. 대표: 렌더 동작 자동 테스트 없음(브라우저 확인에 의존), 375px에서 3겹 인용 폭 43px. 전체: [F7 실행 보고서](../impl-reports/F7.md) |
| F10 | 저장소 장애 처리 | 완료 | 2026-11-01 | minor 9건, info 3건. 대표: 시작 실패 때 uvicorn 추적 출력이 붙음, `file:` 또는 `uri=true` URL은 700/600 처리 밖, `.env` 읽기 실패 문구 없음, 쿼리 키 반복 URL은 `시작 실패:` 줄 없이 끝남. 전체: [F10 실행 보고서](../impl-reports/F10.md) |
