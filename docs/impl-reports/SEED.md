# 실행 보고서: SEED 초기 데이터 시드 스크립트

## 결과
- 테스트 루프: 0회 / 리뷰 라운드: 0회 / 테스트 통과: 702/702

## 한 일
- `scripts/seed_bigdata.py`를 만들었다. 주제 1개, 공부 기록 4건, 노트 6건을 한 트랜잭션으로 넣는다.
- 원문은 저장소에 없어 설계 세션 첫 메시지의 붙여 넣은 노트를 썼다. 합계 360분과 4일이 설계 예시와 같다.
- 같은 이름의 주제가 있으면 아무것도 바꾸지 않고 끝난다. 실제 DB(`data/study.db`)에는 실행하지 않았다.

## 바뀐 파일
- scripts/seed_bigdata.py
- tests/test_seed.py

## 이번에 정한 해석
- SEED: 시드 원문은 저장소에 없어 설계 세션의 첫 메시지에 붙여 넣은 노트를 쓴다. 공부 기록 합계 360분과 4일이 5절 예시와 같다.
- SEED: 같은 이름의 주제가 이미 있으면 아무것도 바꾸지 않고 건너뛴다(중복 생성 없음, 기존 데이터 수정 없음).
- SEED: 사용자 글은 고치지 않고 그대로 넣는다(원문의 오타 포함). 후기의 항목들은 노트 6건에 맞춰 "코딩팡 사용" 한 건에 모은다.

## 남은 지적 (minor, info)
- (minor) scripts/seed_bigdata.py:110: 프로젝트 폴더 밖에서 실행하면 다른 새 DB에 넣고도 성공 문구가 나온다. 대상 경로를 출력하거나 멈춘다 - reviewer, security
- (minor) scripts/seed_bigdata.py:126: 안쪽 `db.rollback()`이 중복이다 - reviewer
- (minor) tests/test_seed.py:180: 중간 실패 시 아무것도 남지 않는지, `.env` 경유 경로를 확인하는 테스트가 없다 - reviewer
- (minor) tests/test_seed.py:51: `setdefault` 두 줄과 주석이 필요 없다 - reviewer
- (info) scripts/seed_bigdata.py:127: 시드 값이 Pydantic 검증을 거치지 않는다. 현재 값은 제약을 모두 지킨다 - reviewer
- (info) scripts/seed_bigdata.py:111: DB 폴더 만드는 코드가 main.py와 같다 - reviewer
- (info) 노트 제목 4개(1, 2, 4번 등)는 원문에 없어 지휘자가 지었다. 사용자가 원문과 대조하면 좋다 - reviewer
- (info) 5절 F2 예시의 "시나공 ch3" 메모는 원문에 없어 넣지 않았다 - reviewer

## 사용자 테스트 목록
- 준비: 프로젝트 폴더에서 `source .venv/bin/activate && python scripts/seed_bigdata.py`
- [ ] 실행 문구 → "주제 1건, 공부 기록 4건, 노트 6건 (합계 360분)"
- [ ] S2 → 빅데이터분석기사 실기 카드에 6h, 노트 6, 미해결 1이 보인다
- [ ] S3 → 공부 기록 4건, 노트 6건, 태그 칩 csv, datetime, pandas가 보인다
- [ ] 노트 제목과 내용이 원래 쓰던 노트와 맞는지 본다
- [ ] 다시 실행 → "이미 있습니다"가 나오고 아무것도 늘지 않는다
