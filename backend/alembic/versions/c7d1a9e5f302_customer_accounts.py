"""customer accounts, and whose order an online order is

Additive only (a new table with row-level security, a nullable column, a column with a default), so it can be
applied to Supabase before the code that uses it.

Revision ID: c7d1a9e5f302
Revises: b4bb997f2f3c
Create Date: 2026-10-21 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d1a9e5f302'
down_revision: Union[str, Sequence[str], None] = 'b4bb997f2f3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('customer_accounts',
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone')
    )
    op.execute("ALTER TABLE customer_accounts ENABLE ROW LEVEL SECURITY")
    op.add_column('food_courts', sa.Column('location', sa.String(length=120), server_default='', nullable=False))
    op.add_column('online_orders', sa.Column('customer_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_online_orders_customer_id'), 'online_orders', ['customer_id'], unique=False)
    op.create_foreign_key(
        'fk_online_orders_customer', 'online_orders', 'customer_accounts', ['customer_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_online_orders_customer', 'online_orders', type_='foreignkey')
    op.drop_index(op.f('ix_online_orders_customer_id'), table_name='online_orders')
    op.drop_column('online_orders', 'customer_id')
    op.drop_column('food_courts', 'location')
    op.drop_table('customer_accounts')
