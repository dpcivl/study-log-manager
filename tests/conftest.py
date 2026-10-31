"""공용 픽스처. 각 테스트는 빈 :memory: SQLite로 시작한다.

- `client`: 로그인하지 않은 TestClient
- `auth_client`: TEST_PASSWORD로 POST /api/login을 마친 TestClient
- `TEST_PASSWORD`: 테스트 앱의 APP_PASSWORD
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

TEST_PASSWORD = "test-password"
TEST_SECRET_KEY = "test-secret-key"


def make_settings(**overrides) -> Settings:
    values = {
        "app_password": TEST_PASSWORD,
        "secret_key": TEST_SECRET_KEY,
        "database_url": "sqlite:///:memory:",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    response = client.post("/api/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 204, response.text
    return client
