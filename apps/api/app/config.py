from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:password@localhost:5434/caselink"
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    keycloak_issuer: str = "http://localhost:8080/realms/copilot"
    keycloak_audience: str = "copilot-api"
    keycloak_jwks_cache_ttl_seconds: int = 300

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()


def jwks_url() -> str:
    return f"{settings.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"
