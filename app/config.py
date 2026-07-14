from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ecuador Public Spending Monitor"
    environment: str = "development"
    database_url: str = "sqlite:///./data/processed/monitor.db"
    log_level: str = "INFO"
    premium_token: str = ""
    admin_token: str = ""
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    alert_from_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
