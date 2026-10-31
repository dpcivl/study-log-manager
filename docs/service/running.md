# 실행과 백업

## 1. 설정 (.env)
프로젝트 루트에 `.env` 파일을 만들고 아래 세 값을 채운다. `.env`는 저장소에 올리지 않는다(`.gitignore`).

```bash
cp .env.example .env
```

- `APP_PASSWORD`: 로그인에 쓰는 비밀번호.
- `SECRET_KEY`: 세션 쿠키 서명 키. 아래 명령으로 만든다.
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `DATABASE_URL`: 기본값 `sqlite:///data/study.db`.

### 비밀번호를 바꿀 때
`APP_PASSWORD`를 바꾸면 `SECRET_KEY`도 함께 바꾼다. `SECRET_KEY`가 바뀌면 기존 세션 쿠키가 모두 무효화되어 다시 로그인해야 한다. `SECRET_KEY`를 그대로 두면 이전 비밀번호로 발급된 세션이 30일 동안 살아 있다.

## 2. 실행
설치(처음 한 번)
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

개발 중 실행(코드 변경 시 자동 재시작)
```bash
uvicorn app.main:app --app-dir src --reload --port 8000
```

운영 실행 명령(`--reload` 없이)
```bash
uvicorn app.main:app --app-dir src --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips='<프록시 IP>'
```

### 리버스 프록시(HTTPS) 뒤에서 운영할 때
- 반드시 `--proxy-headers --forwarded-allow-ips='<프록시 IP>'`를 붙인다.
  - 이 옵션이 없으면 모든 사용자가 프록시 IP 하나로 묶여, 한 사람이 5번 틀리면 다른 사람까지 60초 동안 로그인이 막힌다.
  - 옵션이 있으면 로그인 잠금이 사용자(실제 IP)별로 나뉜다.
- HTTPS로 접속하면 세션 쿠키에 `Secure`가 붙는다. 이 판정도 위 옵션에 의존하므로 HTTPS 운영이면 옵션을 빠뜨리지 않는다.
- `<프록시 IP>`에는 앞단 프록시(예: nginx)가 연결해 오는 주소를 적는다.

## 3. 백업
- 데이터는 `data/study.db` 한 파일에 있다.
- 백업은 서버를 멈춘 상태에서 이 파일을 다른 곳에 복사하는 것이다.
  ```bash
  cp data/study.db 백업_경로/study-$(date +%Y%m%d).db
  ```
- 서버가 도는 중에 복사하면 쓰는 중인 내용이 빠질 수 있으므로 멈춘 뒤에 복사한다.
- 복원은 서버를 멈춘 뒤 백업 파일을 `data/study.db`로 덮어쓰고 다시 실행한다.

## 4. 초기 데이터 넣기 (시드)
처음 써 볼 때 샘플 데이터(주제 1개, 공부 기록 4건, 노트 6건)를 넣는다.
반드시 프로젝트 폴더에서 실행한다. 앱과 같은 `.env`의 DB에 넣기 때문이다.
```bash
source .venv/bin/activate && python scripts/seed_bigdata.py
```
- 같은 이름의 주제가 이미 있으면 아무것도 바꾸지 않고 끝난다.
