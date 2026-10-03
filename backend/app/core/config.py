from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file).

    There is deliberately no default for JWT_SECRET: a missing secret must crash
    the app at startup rather than silently sign tokens with a known value.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://chai:chai@localhost:5432/chai_pos"
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("jwt_secret")
    @classmethod
    def no_placeholder_secret_in_prod(cls, v: str, info):
        if info.data.get("env") == "prod" and "change-me" in v:
            raise ValueError("JWT_SECRET still has the placeholder value")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
