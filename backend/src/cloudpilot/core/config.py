from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    app_name: str = Field(default="CloudPilot AI", min_length=1, max_length=100)
    app_version: str = "0.1.0"
    environment: Literal["development", "testing", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: SecretStr
    cors_origins: list[str] = ["http://localhost:15173", "http://127.0.0.1:15173"]

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("Use postgresql+psycopg and a database name")
        return value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, values: list[str]) -> list[str]:
        for origin in values:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
                or "*" in origin
            ):
                raise ValueError("CORS requires explicit HTTP(S) origins without paths")
        return values

    @model_validator(mode="after")
    def production_settings(self) -> "Settings":
        if self.environment == "production":
            url = make_url(self.database_url.get_secret_value())
            if not url.password or len(url.password) < 24:
                raise ValueError(
                    "Production requires a database password of at least 24 characters"
                )
            if not self.cors_origins or any(
                not origin.startswith("https://") for origin in self.cors_origins
            ):
                raise ValueError("Production requires explicit HTTPS CORS origins")
            if url.query.get("sslmode") not in {"verify-ca", "verify-full"}:
                raise ValueError("Production requires verified database TLS")
        return self
