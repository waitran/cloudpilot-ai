import pytest
from cloudpilot.core.config import Settings
from pydantic import ValidationError
from sqlalchemy.engine import make_url


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        config()


def test_secret_is_masked(settings):
    assert "tester@" not in repr(settings)


@pytest.mark.parametrize("url", ["sqlite:///db", "invalid", "postgresql://host/db"])
def test_non_psycopg_connections_are_rejected(url):
    with pytest.raises(ValidationError):
        config(database_url=url)


@pytest.mark.parametrize("origins", [["*"], ["https://example.com/path"], ["null"]])
def test_unsafe_origins_are_rejected(settings, origins):
    with pytest.raises(ValidationError):
        config(database_url=settings.database_url, cors_origins=origins)


def test_production_rejects_development_defaults(settings):
    with pytest.raises(ValidationError):
        config(database_url=settings.database_url, environment="production")


def test_production_requires_verified_tls():
    password = "x" * 32
    with pytest.raises(ValidationError):
        config(
            database_url=make_url("postgresql+psycopg://app@db/app")
            .set(password=password)
            .render_as_string(hide_password=False),
            environment="production",
            cors_origins=["https://app.example.com"],
        )


def test_explicit_production_settings_are_accepted():
    password = "x" * 32
    settings = config(
        database_url=make_url("postgresql+psycopg://app@db/app?sslmode=verify-full")
        .set(password=password)
        .render_as_string(hide_password=False),
        environment="production",
        cors_origins=["https://app.example.com"],
    )
    assert settings.environment == "production"


def test_invalid_settings_do_not_print_credentials():
    password = "private-value-for-validation-check"
    url = make_url("postgresql+psycopg://app@db/app").set(password=password)
    with pytest.raises(ValidationError) as error:
        config(
            database_url=url.render_as_string(hide_password=False),
            environment="production",
        )
    assert password not in str(error.value)
