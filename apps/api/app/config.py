from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:password@localhost:5434/caselink"
    migration_database_url: str | None = None
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    keycloak_issuer: str = "http://localhost:8080/realms/copilot"
    keycloak_audience: str = "copilot-api"
    keycloak_jwks_cache_ttl_seconds: int = 300
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_ROOT_USER", "MINIO_ACCESS_KEY"),
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_ROOT_PASSWORD", "MINIO_SECRET_KEY"),
    )
    minio_secure: bool = False
    originals_bucket: str = "originals"
    originals_retention_mode: Literal["GOVERNANCE", "COMPLIANCE"] = "GOVERNANCE"
    originals_retention_days: int = Field(default=1, ge=1)
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    redis_url: str = "redis://localhost:6379/0"
    redis_publish_timeout_seconds: float = Field(default=0.3, gt=0)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()


def jwks_url() -> str:
    return f"{settings.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"
