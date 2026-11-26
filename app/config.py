from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    credential_key: SecretStr
    cookie_secure: bool = False
    session_hours: int = Field(default=24, ge=1, le=720)
    expiry_interval_seconds: int = Field(default=30, ge=1, le=3600)

    # Monobank acquiring. An empty token disables payments (HTTP 503).
    monobank_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("MONOBANK_TOKEN", "MONOBANK_TEST_TOKEN"),
    )
    monobank_api_url: str = "https://api.monobank.ua"
    monobank_wallet_prefix: str = Field(
        default="vpsrent", pattern=r"^[A-Za-z0-9_-]{1,32}$"
    )
    # Address customers use to reach the app. Used for the redirect after
    # payment and, when it is https, for Monobank webhooks.
    public_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("PUBLIC_URL", "MONOBANK_PUBLIC_URL"),
    )
    payment_validity_seconds: int = Field(default=3600, ge=300, le=86400)
    auto_renew_days_before: int = Field(default=3, ge=1, le=25)
    auto_renew_retry_hours: int = Field(default=12, ge=1, le=72)

    # Google sign-in requires both OAuth credentials.
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")

    @property
    def google_redirect_uri(self) -> str | None:
        if not self.google_client_id:
            return None
        return f"{self.public_url}/api/auth/google/callback"

    @field_validator("public_url")
    @classmethod
    def clean_public_url(cls, value: str) -> str:
        value = value.strip().rstrip("/") or "http://127.0.0.1:8000"
        parts = urlsplit(value)
        if (
            not parts.hostname
            or parts.username
            or parts.password
            or parts.path
            or parts.query
            or parts.fragment
            or parts.scheme not in {"http", "https"}
            or (
                parts.scheme == "http"
                and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("PUBLIC_URL must be HTTPS or a localhost origin")
        return value

    @property
    def webhook_url(self) -> str | None:
        if not self.public_url.startswith("https://"):
            return None
        return f"{self.public_url}/api/payments/monobank/webhook"

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use PostgreSQL with psycopg")
        return value

    @field_validator("credential_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        Fernet(value.get_secret_value().encode())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
