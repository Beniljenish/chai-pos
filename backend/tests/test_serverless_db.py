"""The serverless DB mode used on Vercel + Supabase's transaction pooler."""

from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import make_engine


def test_serverless_mode_has_no_pool_and_no_prepared_statements():
    settings = get_settings().model_copy(update={"db_serverless": True})
    engine = make_engine(settings)
    try:
        assert isinstance(engine.pool, NullPool)
        with engine.connect() as conn:
            # psycopg prepares a statement after 5 runs by default; through a
            # transaction pooler that breaks. With prepare_threshold=None it never does.
            for _ in range(10):
                assert conn.execute(text("select 1")).scalar() == 1
            assert conn.connection.dbapi_connection.prepare_threshold is None
            prepared = conn.execute(text("select count(*) from pg_prepared_statements")).scalar()
            assert prepared == 0
    finally:
        engine.dispose()


def test_default_mode_keeps_a_pool():
    engine = make_engine(get_settings().model_copy(update={"db_serverless": False}))
    try:
        assert not isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()
