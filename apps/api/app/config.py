from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:password@localhost:5434/caselink"
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
