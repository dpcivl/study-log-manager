# 실행과 백업

## 1. 설정 (.env)
프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채운다. `.env`는 저장소에 올리지 않는다(`.gitignore`).

```bash
cp .env.example .env
chmod 600 .env
```

- `PUBLIC_DEPLOY`: 기본은 `false`(로컬). 인터넷에 공개할 때는 반드시 `true`로 둔다.
  - `true`: `SECRET_KEY`가 32자 미만이거나, `APP_PASSWORD`가 12자 미만(앞뒤 공백 제외)이거나 비어 있으면 앱이 시작을 거부한다. 세션 쿠키에 항상 `Secure`가 붙는다.
  - `false`: 약한 값이어도 시작하지만 경고가 로그에 남는다. 이 상태에서 공개하면 안 된다.
- `APP_PASSWORD`: 로그인에 쓰는 비밀번호. 길고 추측하기 어려운 값을 쓴다. `study1234`는 공개 저장소에 있는 목업 값이므로 쓰지 않는다.
- `SECRET_KEY`: 세션 쿠키 서명 키. 아래 명령으로 만든다.
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `DATABASE_URL`: 기본값 `sqlite:///data/study.db`.

### 파일 권한
`.env`, `data/`, 백업 파일은 소유자만 읽을 수 있게 둔다.
```bash
chmod 600 .env
chmod 700 data
chmod 600 백업_경로/study-YYYYMMDD.db
```

### 비밀번호를 바꿀 때
`APP_PASSWORD`를 바꾸면 `SECRET_KEY`도 함께 바꾼다. `SECRET_KEY`가 바뀌면 기존 세션 쿠키가 모두 무효화되어 다시 로그인해야 한다. `SECRET_KEY`를 그대로 두면 이전 비밀번호로 발급된 세션이 30일 동안 살아 있다.

### 토큰 유출이나 기기 분실 때
`SECRET_KEY`를 새로 만들어 바꾸면 모든 세션이 끊긴다. 위 생성 명령으로 새 값을 만들고 서버를 다시 시작한다.

## 2. 실행
설치(처음 한 번)
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

운영 설치(해시로 잠근 의존성)
```bash
pip install --require-hashes -r requirements-prod.lock
```

개발 중 실행(코드 변경 시 자동 재시작)
```bash
uvicorn app.main:app --app-dir src --reload --port 8000
```

운영 실행(`--reload` 없이)
```bash
PUBLIC_DEPLOY=true uvicorn app.main:app --app-dir src --host 127.0.0.1 --port 8000 --http h11 --workers 1 --no-server-header --forwarded-allow-ips='<프록시 IP>'
```
- `PUBLIC_DEPLOY=true`: 공개 배포 표시. 위 1절의 검사와 `Secure` 쿠키가 켜진다.
- `--http h11`: 요청 헤더 크기 상한을 두기 위한 것. httptools는 헤더 누적 상한이 없을 수 있다.
- `--workers 1`: 로그인 실패 카운터가 프로세스마다 따로 있으므로 워커를 늘리면 잠금 횟수가 나뉜다.
- `--no-server-header`: 서버 종류와 버전을 응답에 싣지 않는다.
- `--forwarded-allow-ips='<프록시 IP>'`: 프록시 규칙은 아래 3절 참고.

### 접근 로그
접근 로그에는 검색어와 태그가 쿼리 문자열로 남는다. 원치 않으면 운영 실행 명령에 `--no-access-log`를 붙인다.

## 3. 리버스 프록시 규칙(HTTPS)
- 프록시에서 HTTPS를 끝낸다.
- 프록시는 `X-Forwarded-For`와 `X-Forwarded-Proto`를 클라이언트가 보낸 값에 덧붙이지 말고 **덮어쓴다**. nginx 예:
  ```nginx
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header X-Forwarded-Proto https;
  ```
- `--forwarded-allow-ips='*'`는 쓰지 않는다. 클라이언트가 보낸 값이 그대로 로그인 잠금 키가 되어 5회 제한이 무력화된다.
- uvicorn은 프록시 헤더를 기본으로 믿고, 127.0.0.1과 ::1을 신뢰한다.
  - 프록시가 같은 서버에 있으면 옵션이 없어도 헤더를 믿으므로, 위 덮어쓰기가 꼭 필요하다.
  - 프록시가 다른 주소에 있으면 `--forwarded-allow-ips`에 그 주소를 적는다. 적지 않으면 모든 접속이 프록시 IP 하나로 묶여, 누군가 5번 틀리면 주인도 60초 동안 로그인이 막힌다.
- 프록시가 다른 서버에 있으면 `--host 127.0.0.1`을 앱이 프록시와 통신할 주소로 바꾸고, 그 포트는 프록시 서버에서만 열어야 한다. 외부에서 앱 포트에 직접 닿으면 클라이언트가 헤더를 직접 넣을 수 있다.
- CDN이나 2단 프록시 뒤에서는 `$remote_addr`가 CDN 또는 앞단 프록시 주소라서 모든 요청이 한 IP로 묶인다. 프록시 단계마다 실제 클라이언트 IP를 복원한 뒤 `X-Forwarded-For`를 그 값으로 덮어써야 한다.
- 프록시 없이 직접 공개하지 않는다. 앞단에 다음 제한을 둔다.
  - 요청 헤더 크기 상한
  - 본문 크기 상한(앱의 본문 상한은 1MiB)
  - 본문 수신 시간 제한
  - 연결 수 제한
  - `Host` 헤더: 허용한 도메인만 통과시킨다. nginx 예(인증서 경로는 자리표시):
    ```nginx
    server {
        listen 443 ssl;
        server_name 허용도메인.example;
        ssl_certificate <인증서 경로>;
        ssl_certificate_key <개인키 경로>;
        location / {
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto https;
            proxy_pass http://127.0.0.1:8000;
        }
    }
    server {
        listen 80;
        server_name 허용도메인.example;
        return 301 https://$host$request_uri;
    }
    server {
        listen 443 ssl default_server;
        server_name _;
        ssl_certificate <인증서 경로>;
        ssl_certificate_key <개인키 경로>;
        return 444;
    }
    ```
- HSTS는 HTTPS 배포에서 켠다. `PUBLIC_DEPLOY=true`이면 앱이 응답에 HSTS 헤더를 보낸다.
- 응답 캐시는 `/api` 경로에 적용하지 않는다.
- `<프록시 IP>`에는 앞단 프록시가 앱에 연결해 오는 주소를 적는다.
- uvicorn 파서의 400과 프록시 자체 오류 페이지에는 앱의 보안 헤더가 붙지 않는다. 필요하면 프록시에서도 HSTS와 nosniff를 붙인다. nginx 예: `add_header Strict-Transport-Security "max-age=31536000" always;`, `add_header X-Content-Type-Options nosniff always;`
- 한계: 제한은 IP 단위라서 주소를 많이 가진 공격자는 제한을 나눠 피할 수 있다. 전역 상한은 주인까지 잠글 수 있어 두지 않았다. 12자 이상의 무작위 비밀번호가 남은 방어선이다.

### 동작 확인
1. 시도마다 `X-Forwarded-For` 값을 다르게 넣어 틀린 비밀번호를 6번 보낸다. 1~5번째는 401 `invalid_password`, 6번째는 429 `too_many_attempts`여야 한다. 429가 안 나오면 프록시가 헤더를 덮어쓰지 않는 것이다. 위 3절의 규칙을 다시 본다.
   잠금이 풀리도록 60초 기다린다.
2. 프록시 뒤에서 한 IP로 비밀번호를 일부러 6번 틀린다. 1~5번째는 401, 6번째 응답이 429 `too_many_attempts`인지 본다.
   잠금이 풀리도록 60초 기다린다.
3. 다른 IP에서 로그인해 보고, 앞의 잠금에 영향을 받지 않는지 본다.
   잠금이 풀리도록 60초 기다린다.
4. 로그인 응답의 `Set-Cookie`에 `Secure`가 있는지 본다.
   ```bash
   curl -i -X POST https://<도메인>/api/login -H 'Content-Type: application/json' -d '{"password":"<비밀번호>"}'
   ```

## 4. 백업
- 데이터는 `data/study.db` 한 파일에 있다.
- 백업은 서버를 멈춘 상태에서 이 파일을 다른 곳에 복사하는 것이다.
  ```bash
  cp data/study.db 백업_경로/study-$(date +%Y%m%d).db
  chmod 600 백업_경로/study-$(date +%Y%m%d).db
  ```
- 서버가 도는 중에 복사하면 쓰는 중인 내용이 빠질 수 있으므로 멈춘 뒤에 복사한다.
- 복원은 서버를 멈춘 뒤 백업 파일을 `data/study.db`로 덮어쓰고 다시 실행한다.

## 5. 초기 데이터 넣기 (시드)
처음 써 볼 때 샘플 데이터(주제 1개, 공부 기록 4건, 노트 6건)를 넣는다.
반드시 프로젝트 폴더에서 실행한다. 앱과 같은 `.env`의 DB에 넣기 때문이다.
```bash
source .venv/bin/activate && python scripts/seed_bigdata.py
```
- 같은 이름의 주제가 이미 있으면 아무것도 바꾸지 않고 끝난다.
