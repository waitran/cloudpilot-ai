import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cloudpilot.core.config import Settings
from cloudpilot.db.database import Database
from cloudpilot.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_settings(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not provided: PostgreSQL integration was not executed")
    # Destructive migration checks must never target the development or production database.
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with _test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    return Settings(_env_file=None)


def test_real_postgres_and_migration_roundtrip(postgres_settings):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    database = Database(postgres_settings)
    try:
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT current_database()")).endswith("_test")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001_initial"
            )
        assert database.reachable()
        with database.sessions() as session:
            assert session.scalar(text("SELECT 1")) == 1
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        database.close()


def test_api_with_real_postgres(postgres_settings):
    with TestClient(create_app(postgres_settings)) as client:
        assert client.get("/api/v1/health/ready").json()["status"] == "ready"
        assert client.get("/api/v1/health/ready").status_code == 200
        response = client.get("/api/v1/system/info")
        assert response.status_code == 200
        assert response.json()["components"]["postgresql"]["status"] == "available"
