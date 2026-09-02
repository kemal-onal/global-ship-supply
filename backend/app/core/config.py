"""
Application configuration using Pydantic Settings.
Supports environment-specific configs with validation.
"""
import secrets
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import (
    AnyHttpUrl,
    BeforeValidator,
    EmailStr,
    Field,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    PROJECT_NAME: str = "AVS Global Ship Supply Management"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "RS256"
    ENVIRONMENT: Literal["local", "development", "staging", "production"] = "local"

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "avs_global"
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_POOL_TIMEOUT: int = 30

    # Full async URL (overrides POSTGRES_* when set)
    DATABASE_URL: str | None = None
    SYNC_DATABASE_URL: str | None = None

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=f"/{self.POSTGRES_DB}",
        )

    @computed_field
    @property
    def SQLALCHEMY_SYNC_DATABASE_URI(self) -> str:
        if self.SYNC_DATABASE_URL:
            return self.SYNC_DATABASE_URL
        return PostgresDsn.build(
            scheme="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=f"/{self.POSTGRES_DB}",
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0

    @computed_field
    @property
    def REDIS_URI(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # CORS
    BACKEND_CORS_ORIGINS: Annotated[list[AnyHttpUrl] | str, BeforeValidator(parse_cors)] = []

    # Security
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    JWT_PUBLIC_KEY_PATH: str = "keys/public.pem"
    JWT_PRIVATE_KEY_PATH: str = "keys/private.pem"
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 1
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Email (for RFQ notifications)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    EMAILS_FROM_EMAIL: EmailStr = "noreply@avsglobal.com"
    EMAILS_FROM_NAME: str = "AVS Global"

    # VSAT / Offline Sync
    SYNC_BATCH_SIZE: int = 100
    SYNC_INTERVAL_SECONDS: int = 30
    MAX_OFFLINE_QUEUE_SIZE: int = 10000
    CONFLICT_RESOLUTION_STRATEGY: Literal["server_wins", "client_wins", "merge", "manual"] = "merge"

    # Supplier Bidding
    RFQ_RESPONSE_TIMEOUT_HOURS: int = 48
    MIN_SUPPLIERS_PER_RFQ: int = 3
    SUPPLIER_SCORE_WEIGHT_PRICE: float = 0.5
    SUPPLIER_SCORE_WEIGHT_LEAD_TIME: float = 0.2
    SUPPLIER_SCORE_WEIGHT_RELIABILITY: float = 0.2
    SUPPLIER_SCORE_WEIGHT_QUALITY: float = 0.1

    # Catering
    DEFAULT_CREW_NATIONALITIES: list[str] = ["Filipino", "Indian", "European", "Chinese", "Turkish"]
    CALORIE_TARGET_PER_PERSON_PER_DAY: int = 3200
    PROVISIONING_BUFFER_DAYS: int = 7
    PROVISIONING_BUFFER_PERCENT: float = 0.15

    # Customs/Regulations
    REGULATIONS_UPDATE_INTERVAL_HOURS: int = 24
    HS_CODE_API_URL: str = "https://api.customs.gov/hs-codes"
    IMPA_CATALOG_URL: str = "https://catalog.impa.com/api"

    # Monitoring
    SENTRY_DSN: str | None = None
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True
    TRACING_ENABLED: bool = True

    @model_validator(mode="after")
    def _validate_keys_exist(self) -> Self:
        if self.ENVIRONMENT == "production":
            # In production, keys should exist
            pass
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()