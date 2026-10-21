"""super admin: platform_admins, and food courts that belong to no shop

Additive or relaxing only (a new table with row-level security, a nullable column, two
columns made optional), so it can be applied to Supabase before the code that uses it.
join_code is retired but kept (nullable) so dropping it is a later, separate step.

Revision ID: b4bb997f2f3c
Revises: 027da6efe82c
Create Date: 2026-10-21 14:40:44.540803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4bb997f2f3c'
down_revision: Union[str, Sequence[str], None] = '027da6efe82c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('platform_admins',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone')
    )
    op.add_column('food_courts', sa.Column('created_by', sa.UUID(), nullable=True))
    op.alter_column('food_courts', 'join_code',
               existing_type=sa.VARCHAR(length=12),
               nullable=True)
    op.alter_column('food_courts', 'host_shop_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.create_foreign_key(
        'fk_food_courts_created_by', 'food_courts', 'platform_admins', ['created_by'], ['id'], ondelete='RESTRICT'
    )
    op.execute("ALTER TABLE platform_admins ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    # Courts made by an admin have no host shop or code: delete those before going back.
    op.execute("DELETE FROM food_court_outlets WHERE court_id IN (SELECT id FROM food_courts WHERE host_shop_id IS NULL)")
    op.execute("DELETE FROM online_orders WHERE court_id IN (SELECT id FROM food_courts WHERE host_shop_id IS NULL)")
    op.execute("DELETE FROM food_courts WHERE host_shop_id IS NULL")
    op.drop_constraint('fk_food_courts_created_by', 'food_courts', type_='foreignkey')
    op.alter_column('food_courts', 'host_shop_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.alter_column('food_courts', 'join_code',
               existing_type=sa.VARCHAR(length=12),
               nullable=False)
    op.drop_column('food_courts', 'created_by')
    op.drop_table('platform_admins')
