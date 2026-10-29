from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration. Secrets are never printed or logged."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Airline Contact Center AI Platform"
    default_employee_language: Literal["en", "ar", "fr"] = "en"

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = "db_airlines"
    db_user: str = "root"
    db_password: SecretStr = SecretStr("root")
    db_connect_timeout: int = Field(default=5, ge=1, le=60)

    llm_provider: Literal["ollama", "openai"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""

    chroma_persist_directory: str = "./local_data/chroma"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached, validated settings instance."""
    return Settings()
