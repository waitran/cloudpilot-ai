import pytest
from cloudpilot.core.config import Settings
from cloudpilot.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://tester@127.0.0.1:1/cloudpilot_test",
        environment="testing",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client
