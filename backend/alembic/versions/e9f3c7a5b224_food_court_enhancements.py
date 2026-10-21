"""food court extras: dish description/photo/veg, wait time, ratings, favourites, push

Additive only (new tables with row-level security; new columns with defaults or nullable), so it
can be applied to Supabase before the code that uses it.

Revision ID: e9f3c7a5b224
Revises: d8e2b6f4a113
Create Date: 2026-10-21 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f3c7a5b224'
down_revision: Union[str, Sequence[str], None] = 'd8e2b6f4a113'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('menu_items', sa.Column('description', sa.String(length=200), server_default='', nullable=False))
    op.add_column('menu_items', sa.Column('photo_url', sa.String(length=500), server_default='', nullable=False))
    op.add_column('menu_items', sa.Column('is_veg', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('food_court_outlets', sa.Column('prep_minutes', sa.Integer(), nullable=True))
    op.add_column('online_orders', sa.Column('ready_notified_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('order_feedback',
    sa.Column('online_order_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('comment', sa.String(length=200), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_order_feedback_rating'),
    sa.ForeignKeyConstraint(['customer_id'], ['customer_accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['online_order_id'], ['online_orders.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('online_order_id', name='uq_order_feedback_order')
    )
    op.create_index(op.f('ix_order_feedback_customer_id'), 'order_feedback', ['customer_id'], unique=False)
    op.create_index(op.f('ix_order_feedback_shop_id'), 'order_feedback', ['shop_id'], unique=False)

    op.create_table('customer_favourites',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.Column('menu_item_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('customer_id', 'menu_item_id', name='uq_customer_favourite')
    )
    op.create_index(op.f('ix_customer_favourites_customer_id'), 'customer_favourites', ['customer_id'], unique=False)

    op.create_table('push_subscriptions',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('endpoint', sa.String(length=600), nullable=False),
    sa.Column('p256dh', sa.String(length=200), nullable=False),
    sa.Column('auth', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer_accounts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint')
    )
    op.create_index(op.f('ix_push_subscriptions_customer_id'), 'push_subscriptions', ['customer_id'], unique=False)

    for table in ('order_feedback', 'customer_favourites', 'push_subscriptions'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_push_subscriptions_customer_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_index(op.f('ix_customer_favourites_customer_id'), table_name='customer_favourites')
    op.drop_table('customer_favourites')
    op.drop_index(op.f('ix_order_feedback_shop_id'), table_name='order_feedback')
    op.drop_index(op.f('ix_order_feedback_customer_id'), table_name='order_feedback')
    op.drop_table('order_feedback')
    op.drop_column('online_orders', 'ready_notified_at')
    op.drop_column('food_court_outlets', 'prep_minutes')
    op.drop_column('menu_items', 'is_veg')
    op.drop_column('menu_items', 'photo_url')
    op.drop_column('menu_items', 'description')
