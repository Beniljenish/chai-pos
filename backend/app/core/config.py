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
    # Serverless hosts (Vercel) run each request in a short-lived instance, and
    # connect through Supabase's transaction pooler (port 6543). There, a
    # connection pool inside the app is useless (the instance may freeze between
    # requests) and server-side prepared statements break (the next query may
    # land on a different Postgres connection). DB_SERVERLESS=true handles both.
    db_serverless: bool = False
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cors_origins: list[str] = ["http://localhost:5173"]
    # The shop's "business day" (for stock and day-end) is in this timezone.
    shop_timezone: str = "Asia/Kolkata"
    # Email (Resend). Without a key, emails queue in the outbox and wait.
    resend_api_key: str = ""
    email_from: str = "Chai POS <reports@beniljenish.dev>"
    # Vercel Cron sends "Authorization: Bearer $CRON_SECRET". Empty = cron disabled.
    cron_secret: str = ""
    # Customer messages by iMessage through Inkbox. Empty key = messages are only
    # written to the outbox (owner's Messages screen), not sent. INKBOX_IDENTITY_ID
    # is needed only with an organisation-wide key (it names the sender).
    inkbox_api_key: str = ""
    inkbox_identity_id: str = ""
    # Where customers open receipt links (this API's public address).
    public_api_url: str = "https://chai-pos-api.vercel.app/api/v1"

    @field_validator("jwt_secret")
    @classmethod
    def no_placeholder_secret_in_prod(cls, v: str, info):
        if info.data.get("env") == "prod" and "change-me" in v:
            raise ValueError("JWT_SECRET still has the placeholder value")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
