"""online payments for food court orders, and what each outlet is owed

Additive only (two new tables with row-level security, three columns on online_orders with
defaults or nullable), so it can be applied to Supabase before the code that uses it.

Revision ID: d8e2b6f4a113
Revises: c7d1a9e5f302
Create Date: 2026-10-21 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8e2b6f4a113'
down_revision: Union[str, Sequence[str], None] = 'c7d1a9e5f302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('online_payments',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('court_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='created', nullable=False),
    sa.Column('method', sa.String(length=10), nullable=True),
    sa.Column('amount_paise', sa.Integer(), nullable=False),
    sa.Column('paid_paise', sa.Integer(), nullable=True),
    sa.Column('provider_order_id', sa.String(length=40), nullable=False),
    sa.Column('provider_payment_id', sa.String(length=40), nullable=True),
    sa.Column('error', sa.String(length=200), server_default='', nullable=False),
    sa.Column('parts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('message_ok', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refunded_paise', sa.Integer(), server_default='0', nullable=False),
    sa.Column('refund_error', sa.String(length=60), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('created', 'paid', 'failed')", name='ck_online_payments_status'),
    sa.CheckConstraint("method IS NULL OR method IN ('upi', 'card')", name='ck_online_payments_method'),
    sa.CheckConstraint('amount_paise > 0', name='ck_online_payments_amount'),
    sa.ForeignKeyConstraint(['court_id'], ['food_courts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['customer_id'], ['customer_accounts.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_order_id'),
    sa.UniqueConstraint('provider_payment_id')
    )
    op.create_index(op.f('ix_online_payments_customer_id'), 'online_payments', ['customer_id'], unique=False)
    op.create_table('online_settlements',
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.Column('amount_paise', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=120), server_default='', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint('amount_paise > 0', name='ck_online_settlements_amount'),
    sa.ForeignKeyConstraint(['created_by'], ['platform_admins.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_online_settlements_shop_id'), 'online_settlements', ['shop_id'], unique=False)
    op.execute("ALTER TABLE online_payments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE online_settlements ENABLE ROW LEVEL SECURITY")
    op.add_column('online_orders', sa.Column('payment_id', sa.UUID(), nullable=True))
    op.add_column('online_orders', sa.Column('paid_paise', sa.Integer(), nullable=True))
    op.add_column('online_orders', sa.Column('refunded_paise', sa.Integer(), server_default='0', nullable=False))
    op.create_index(op.f('ix_online_orders_payment_id'), 'online_orders', ['payment_id'], unique=False)
    op.create_foreign_key(
        'fk_online_orders_payment', 'online_orders', 'online_payments', ['payment_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_online_orders_payment', 'online_orders', type_='foreignkey')
    op.drop_index(op.f('ix_online_orders_payment_id'), table_name='online_orders')
    op.drop_column('online_orders', 'refunded_paise')
    op.drop_column('online_orders', 'paid_paise')
    op.drop_column('online_orders', 'payment_id')
    op.drop_index(op.f('ix_online_settlements_shop_id'), table_name='online_settlements')
    op.drop_table('online_settlements')
    op.drop_index(op.f('ix_online_payments_customer_id'), table_name='online_payments')
    op.drop_table('online_payments')
