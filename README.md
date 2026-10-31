# Study Log Manager
비밀번호 하나로 보호되는 개인용 학습 노트 웹앱.

## 실행 방법
- 설치: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- 설정: `cp .env.example .env` 후 `APP_PASSWORD`, `SECRET_KEY` 채우기
- 서버 실행: `uvicorn app.main:app --app-dir src --reload --port 8000`
- 테스트: `pytest tests/`

## 문서
- [설계 문서](docs/design.md)
