from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    credential_key: SecretStr
    cookie_secure: bool = False
    session_hours: int = Field(default=24, ge=1, le=720)
    expiry_interval_seconds: int = Field(default=30, ge=1, le=3600)

    # Monobank acquiring. An empty token disables payments (HTTP 503).
    monobank_token: SecretStr = SecretStr("")
    monobank_api_url: str = "https://api.monobank.ua"
    monobank_wallet_prefix: str = Field(
        default="vpsrent", pattern=r"^[A-Za-z0-9_-]{1,32}$"
    )
    # Address customers use to reach the app. Used for the redirect after
    # payment and, when it is https, for Monobank webhooks.
    public_url: str = "http://127.0.0.1:8000"
    payment_validity_seconds: int = Field(default=3600, ge=300, le=86400)
    auto_renew_days_before: int = Field(default=3, ge=1, le=25)
    auto_renew_retry_hours: int = Field(default=12, ge=1, le=72)

    @field_validator("public_url")
    @classmethod
    def clean_public_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_URL must start with http:// or https://")
        return value.rstrip("/")

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
