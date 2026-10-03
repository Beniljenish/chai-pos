from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db import tenancy  # noqa: F401  (registers the tenant event hooks)


def make_engine(settings: Settings) -> Engine:
    if settings.db_serverless:
        # One real connection per request, opened and closed by the pooler's
        # side; psycopg must not create named prepared statements.
        return create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args={"prepare_threshold": None},
        )
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = make_engine(get_settings())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
