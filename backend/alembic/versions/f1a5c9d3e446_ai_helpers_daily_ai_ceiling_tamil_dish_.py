"""ai helpers: daily ai ceiling, tamil dish names, gst threshold

Revision ID: f1a5c9d3e446
Revises: e9f3c7a5b224
Create Date: 2026-10-21 21:15:12.461681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a5c9d3e446'
down_revision: Union[str, Sequence[str], None] = 'e9f3c7a5b224'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_usage',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('calls', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('shop_id', 'day', name='uq_ai_usage_shop_day')
    )
    op.create_index(op.f('ix_ai_usage_shop_id'), 'ai_usage', ['shop_id'], unique=False)
    op.execute("ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY")
    op.add_column('menu_items', sa.Column('name_ta', sa.String(length=120), server_default='', nullable=False))
    op.add_column('menu_items', sa.Column('description_ta', sa.String(length=300), server_default='', nullable=False))
    op.add_column('shops', sa.Column('gst_threshold_paise', sa.BigInteger(), nullable=True))

    # Hand-written: the database itself refuses to rewrite a sale, like the stock ledger. A bill
    # can only turn from completed to void (everything else about it must stay identical), and
    # neither bills nor voids can be deleted. The app never did either; now ad-hoc SQL cannot.
    op.execute("""
        CREATE FUNCTION bills_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = '' AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'bills cannot be deleted. Void the bill instead.';
            END IF;
            IF OLD.status = 'completed' AND NEW.status = 'void'
               AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'a bill cannot be edited. Void it and bill again.';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER bills_no_edit_no_delete
        BEFORE UPDATE OR DELETE ON bills
        FOR EACH ROW EXECUTE FUNCTION bills_guard();
    """)
    op.execute("""
        CREATE FUNCTION bill_voids_append_only() RETURNS trigger
        LANGUAGE plpgsql SET search_path = '' AS $$
        BEGIN
            RAISE EXCEPTION 'bill_voids is append-only: % is not allowed.', TG_OP;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER bill_voids_no_update_delete
        BEFORE UPDATE OR DELETE ON bill_voids
        FOR EACH ROW EXECUTE FUNCTION bill_voids_append_only();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS bill_voids_no_update_delete ON bill_voids")
    op.execute("DROP FUNCTION IF EXISTS bill_voids_append_only()")
    op.execute("DROP TRIGGER IF EXISTS bills_no_edit_no_delete ON bills")
    op.execute("DROP FUNCTION IF EXISTS bills_guard()")
    op.drop_column('shops', 'gst_threshold_paise')
    op.drop_column('menu_items', 'description_ta')
    op.drop_column('menu_items', 'name_ta')
    op.drop_index(op.f('ix_ai_usage_shop_id'), table_name='ai_usage')
    op.drop_table('ai_usage')
