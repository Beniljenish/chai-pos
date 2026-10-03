"""Database-level security guarantees that hold whatever the app code does."""

from sqlalchemy import text

from app.db.session import engine


def test_every_table_has_row_level_security_enabled():
    """Supabase's Data API exposes public-schema tables to the public anon key.
    A new table without RLS would be readable by anyone: add it to the RLS
    migration (or a new one) before this test will pass."""
    with engine.connect() as conn:
        missing = (
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity "
                    "ORDER BY 1"
                )
            )
            .scalars()
            .all()
        )
    assert not missing, f"Tables without row-level security: {missing}"
