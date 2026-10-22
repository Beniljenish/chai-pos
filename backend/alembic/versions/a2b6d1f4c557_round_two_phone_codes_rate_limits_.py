"""round two: phone codes, rate limits, outlet fee, pickup time, table name, auto sold out, summary, dish photos

Revision ID: a2b6d1f4c557
Revises: f1a5c9d3e446
Create Date: 2026-10-22 04:50:53.273426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b6d1f4c557'
down_revision: Union[str, Sequence[str], None] = 'f1a5c9d3e446'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('phone_codes',
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('purpose', sa.String(length=10), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_phone_codes_phone'), 'phone_codes', ['phone'], unique=False)
    op.create_table('rate_hits',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rate_hits_key'), 'rate_hits', ['key'], unique=False)
    op.create_table('dish_photos',
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dish_photos_shop_id'), 'dish_photos', ['shop_id'], unique=False)
    op.add_column('customer_accounts', sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('food_court_outlets', sa.Column('fee_bp', sa.Integer(), server_default='0', nullable=False))
    op.add_column('food_court_outlets', sa.Column('pickup_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('food_court_outlets', sa.Column('pickup_capacity', sa.Integer(), server_default='5', nullable=False))
    op.add_column('online_orders', sa.Column('pickup_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('online_orders', sa.Column('table_name', sa.String(length=20), server_default='', nullable=False))
    op.add_column('shops', sa.Column('auto_sold_out', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('shops', sa.Column('summary_phone', sa.String(length=15), nullable=True))
    op.add_column('shops', sa.Column('summary_on', sa.Boolean(), server_default='false', nullable=False))
    for table in ('phone_codes', 'rate_hits', 'dish_photos'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('shops', 'summary_on')
    op.drop_column('shops', 'summary_phone')
    op.drop_column('shops', 'auto_sold_out')
    op.drop_column('online_orders', 'table_name')
    op.drop_column('online_orders', 'pickup_at')
    op.drop_column('food_court_outlets', 'pickup_capacity')
    op.drop_column('food_court_outlets', 'pickup_enabled')
    op.drop_column('food_court_outlets', 'fee_bp')
    op.drop_column('customer_accounts', 'phone_verified_at')
    op.drop_index(op.f('ix_dish_photos_shop_id'), table_name='dish_photos')
    op.drop_table('dish_photos')
    op.drop_index(op.f('ix_rate_hits_key'), table_name='rate_hits')
    op.drop_table('rate_hits')
    op.drop_index(op.f('ix_phone_codes_phone'), table_name='phone_codes')
    op.drop_table('phone_codes')
