from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ecuador Public Spending Monitor"
    environment: str = "development"
    database_url: str = "sqlite:///./data/processed/monitor.db"
    log_level: str = "INFO"
    premium_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

