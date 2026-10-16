from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    redis_url: str = Field(validation_alias="REDIS_URL")
    deribit_base_url: AnyHttpUrl = Field(
        default="https://www.deribit.com/api/v2",
        validation_alias="DERIBIT_BASE_URL",
    )
    deribit_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias="DERIBIT_TIMEOUT_SECONDS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object per process."""
    return Settings()  # type: ignore[call-arg]
