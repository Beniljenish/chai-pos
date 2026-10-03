"""pin search_path on ledger trigger function

Supabase linter 0011: a function without a fixed search_path can be tricked
into resolving names to objects someone else created. The function references
no tables, so an empty search_path is safe and strictest.

Revision ID: 2813bf31e0c6
Revises: d9b48b507dcc
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2813bf31e0c6"
down_revision: str | Sequence[str] | None = "d9b48b507dcc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER FUNCTION stock_ledger_append_only() SET search_path = ''")


def downgrade() -> None:
    op.execute("ALTER FUNCTION stock_ledger_append_only() RESET search_path")
