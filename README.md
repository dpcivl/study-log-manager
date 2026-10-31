# Study Log Manager
비밀번호 하나로 보호되는 개인용 학습 노트 웹앱.

## 실행 방법
- 설치: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (그 뒤 `cp .env.example .env`로 설정, 자세한 내용은 [실행과 백업](docs/service/running.md))
- 서버 실행: `uvicorn app.main:app --app-dir src --reload --port 8000`
- 테스트: `pytest tests/`

## 주요 기능
- F5 비밀번호 로그인

## 문서
- [기능 현황](docs/service/features.md)
- [API](docs/service/api.md)
- [실행과 백업](docs/service/running.md)
- [설계 문서](docs/design.md)
