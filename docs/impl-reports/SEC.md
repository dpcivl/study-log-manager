# 실행 보고서: SEC-1~7 보안 감사 결과 수정

## 결과
- 기준: docs/audit-reports/2026-11-01.md, 재확인: docs/audit-reports/2026-11-01-recheck.md
- 리뷰 수정 라운드: 3회 / 테스트 통과: 1056/1056

## 한 일
- SEC-1: `PUBLIC_DEPLOY`를 켜면 약한 비밀값으로 시작을 거부한다. 끄면 경고를 남긴다. 비밀값은 `SecretStr`로 다룬다.
- SEC-2: 본문 상한 1MiB를 인증 전에 적용한다. 비밀번호 비교는 SHA-256 뒤 `compare_digest`로 한다.
- SEC-3, SEC-4: `Secure`를 설정으로 강제하고, 프록시 규칙과 운영 명령을 running.md에 다시 썼다.
- SEC-5: 화면 로그인 검사 통합, 제어 문자와 만들 수 없는 날짜 거부, 로그아웃 CSRF 방어, IPv6 /64 잠금, 끝 슬래시 리다이렉트 끄기.
- SEC-6: 보안 헤더, `/api` 저장 금지, HSTS, `/openapi.json` 끄기, `hide_parameters`, 405 `Allow`, 잘못된 UTF-8 본문 처리.
- SEC-7: 운영과 개발 의존성 분리, 해시 잠금, pytest 취약점 해소, `.gitignore` 보강.

## 이번에 정한 해석
docs/impl-progress.md의 해석 기록 중 `SEC`로 시작하는 줄이다. 설계 보완 질문 12개는 사용자 지시로 지휘자가 정했고 design.md는 고치지 않았다.

## 남은 지적 (minor, info)
- (minor) 원시 바이트 쿼리의 일부 테스트는 `< 500`만 본다 - reviewer
- (minor) 한 줄 필드에 이미 저장된 탭이 있으면 S4에서 다시 저장할 때 422가 난다. 이번 규칙 이전 데이터에만 해당한다 - reviewer
- (info) 전역 실패 상한을 두지 않아 주소가 많은 공격자는 IP당 제한을 나눠 피할 수 있다 - security
- (info) SEC-4 자동 테스트는 uvicorn을 거치지 않는다. 실제 프록시 동작은 배포 뒤 running.md의 절차로 확인한다 - security
- (info) `Sec-Fetch-Site`가 없는 구형 브라우저와 평문 http에서는 로그아웃 방어가 동작하지 않는다 - security
- (info) 405의 `Allow`는 프레임워크 값이라 일부 메서드만 나온다 - qa

## 사용자 테스트 목록
- 준비: 켜 둔 8000번 서버를 쓴다. 터미널에 `약한 설정으로 시작합니다` 경고가 보이는 것은 정상이다.
- [ ] 주요 화면을 눌러 본다 → 전과 같이 동작한다
- [ ] 노트 제목에 탭이 든 글을 붙여 넣고 저장 → `줄바꿈이나 제어 문자를 쓸 수 없습니다`가 보인다
- [ ] 로그아웃과 다시 로그인 → 정상이다
- [ ] 공개 배포 전 → `.env`의 값을 길게 바꾸고 running.md의 동작 확인 절차를 따른다
