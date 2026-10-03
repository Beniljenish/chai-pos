"""deny by default rls for supabase data api

Supabase publishes every table in the public schema through its Data API
(PostgREST) using the public "anon" key. Without RLS, anyone holding that key
could read password hashes and stock data, bypassing our FastAPI tenant layer.

RLS ON + no policies = the Data API roles (anon, authenticated) see nothing.
Our backend connects as the table owner, which RLS does not restrict, so the
app is unaffected. Harmless on plain Postgres (local dev, CI).

tests/test_database_security.py fails if any future table is missing RLS.

Revision ID: d9b48b507dcc
Revises: 25dd3fc29c46
Create Date: 2026-10-03 08:11:58.144207
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9b48b507dcc"
down_revision: str | Sequence[str] | None = "25dd3fc29c46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "alembic_version",
    "shops",
    "users",
    "devices",
    "refresh_tokens",
    "ingredients",
    "pack_units",
    "menu_items",
    "recipes",
    "recipe_lines",
    "modifiers",
    "modifier_lines",
    "menu_item_modifiers",
    "stock_receipts",
    "prep_batches",
    "stock_ledger",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # Belt and braces on Supabase: also remove the Data API roles' table grants,
    # and stop future tables getting them by default. Skipped where the roles
    # don't exist (local Postgres, CI).
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
              EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
              EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
            END IF;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
