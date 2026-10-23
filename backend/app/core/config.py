from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


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
    email_from: str = "Taptallow <reports@beniljenish.dev>"
    # Vercel Cron sends "Authorization: Bearer $CRON_SECRET". Empty = cron disabled.
    cron_secret: str = ""
    # Customer messages by iMessage through Inkbox. Empty key = messages are only
    # written to the outbox (owner's Messages screen), not sent. INKBOX_IDENTITY_ID
    # is needed only with an organisation-wide key (it names the sender).
    inkbox_api_key: str = ""
    inkbox_identity_id: str = ""
    # Twilio, for phone codes by SMS and the owner's daily message by WhatsApp. The owner types
    # these into the host's settings; they are never in the repo.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_sms_from: str = ""  # a Twilio number in +91... form, or a Messaging Service id (MG...)
    twilio_whatsapp_from: str = ""
    # Customer receipts and "order ready": whatsapp, sms or inkbox; empty = the first one set up.
    customer_messages_channel: str = (
        ""  # the sender's WhatsApp number, +14155238886 for the sandbox
    )
    # Where customers open receipt links (this API's public address).
    public_api_url: str = "https://chai-pos-api.vercel.app/api/v1"
    # Razorpay (test mode first). Empty key = online payments switched off; the
    # app then offers only plain Cash/UPI/Card. The webhook has its own secret.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # Web Push, for "your order is ready" on a customer's phone. Both keys, or push is off.
    # Make a pair with `python -m scripts.make_vapid_keys`; the private one is a secret.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:owner@example.com"  # who the push service may contact
    # LOCAL TESTING ONLY: log in with just a phone number, any password. It refuses
    # to start unless the database is on this computer (or the compose "db"
    # service), so a copy of this setting can never switch it on against Supabase.
    dev_login: bool = False
    # LOCAL TESTING ONLY: customers can "pay online" with pretend money, so the whole ordering
    # flow can be tried without Razorpay keys. Same guard as DEV_LOGIN: never with a remote
    # database or ENV=prod, so it can never reach real customers.
    fake_payments: bool = False
    # AI helpers (README, "9.16"). Empty key = they say "not switched on" and everything else
    # works as before. The key is a secret: the owner types it into Vercel, never into the repo.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"  # claude-haiku-5-5 is about 40x cheaper for these small jobs
    ai_daily_limit: int = 60  # calls per shop per day: a ceiling on cost and on abuse
    # LOCAL TESTING ONLY: a rule-based stand-in for the model, so the AI screens can be tried
    # and tested with no key and no cost. Same guard as FAKE_PAYMENTS.
    fake_ai: bool = False
    # LOCAL TESTING ONLY: phone codes (sign-up check, forgot password) are shown on screen instead
    # of sent by SMS. Same guard as the other pretend modes. With no real SMS sender and this off,
    # customers sign up without a code, as before.
    fake_sms: bool = False

    @model_validator(mode="after")
    def local_test_modes_only_with_a_local_database(self):
        host = make_url(self.database_url).host or ""
        for on, name, what in (
            (self.dev_login, "DEV_LOGIN", "lets anyone in without a password"),
            (self.fake_payments, "FAKE_PAYMENTS", "accepts pretend payments"),
            (self.fake_ai, "FAKE_AI", "answers with a rule-based stand-in instead of a model"),
            (self.fake_sms, "FAKE_SMS", "shows phone codes on screen instead of sending them"),
        ):
            if on and (self.env == "prod" or host not in LOCAL_DB_HOSTS):
                raise ValueError(
                    f"{name} {what}: it is only allowed with a database on this computer "
                    "(localhost or the compose 'db'), and never with ENV=prod"
                )
        return self

    @field_validator("jwt_secret")
    @classmethod
    def no_placeholder_secret_in_prod(cls, v: str, info):
        if info.data.get("env") == "prod" and "change-me" in v:
            raise ValueError("JWT_SECRET still has the placeholder value")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
