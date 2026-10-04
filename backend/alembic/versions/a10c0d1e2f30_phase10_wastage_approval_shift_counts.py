"""phase 10: wastage approval and shift counts; merges the four open heads

Revision ID: a10c0d1e2f30
Revises: 159f8fea95a7, 1dedecb97caa, 59c516ec02c9, feebafd74402
Create Date: 2026-10-04 16:30:00.000000

Additive only (new columns with defaults, a new enum, a new table), so it can be
applied to Supabase before the code that uses it is deployed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a10c0d1e2f30'
down_revision: Union[str, Sequence[str], None] = (
    '159f8fea95a7',
    '1dedecb97caa',
    '59c516ec02c9',
    'feebafd74402',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

wastage_status = postgresql.ENUM('approved', 'pending', 'rejected', name='wastage_status', create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    # 10.2 wastage approval
    wastage_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'shops',
        sa.Column('wastage_approval_paise', sa.Integer(), server_default='20000', nullable=False),
    )
    op.add_column(
        'wastage_entries',
        sa.Column('status', wastage_status, server_default='approved', nullable=False),
    )
    op.add_column(
        'wastage_entries',
        sa.Column('decided_by', sa.UUID(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
    )
    op.add_column('wastage_entries', sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True))

    # 10.3 handover counts
    op.create_table('handover_counts',
    sa.Column('business_date', sa.Date(), nullable=False),
    sa.Column('counted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('counted_by', sa.UUID(), nullable=False),
    sa.Column('shift_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['counted_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_handover_counts_business_date'), 'handover_counts', ['business_date'], unique=False)
    op.create_index(op.f('ix_handover_counts_shop_id'), 'handover_counts', ['shop_id'], unique=False)
    op.create_table('handover_count_lines',
    sa.Column('handover_id', sa.UUID(), nullable=False),
    sa.Column('ingredient_id', sa.UUID(), nullable=False),
    sa.Column('entered', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('loose_qty', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('counted_qty', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('counted_qty >= 0', name='ck_handover_count_lines_counted'),
    sa.ForeignKeyConstraint(['handover_id'], ['handover_counts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('handover_id', 'ingredient_id', name='uq_handover_count_lines_ingredient')
    )
    op.create_index(op.f('ix_handover_count_lines_handover_id'), 'handover_count_lines', ['handover_id'], unique=False)
    op.create_index(op.f('ix_handover_count_lines_shop_id'), 'handover_count_lines', ['shop_id'], unique=False)
    op.execute("ALTER TABLE handover_counts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE handover_count_lines ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_handover_count_lines_shop_id'), table_name='handover_count_lines')
    op.drop_index(op.f('ix_handover_count_lines_handover_id'), table_name='handover_count_lines')
    op.drop_table('handover_count_lines')
    op.drop_index(op.f('ix_handover_counts_shop_id'), table_name='handover_counts')
    op.drop_index(op.f('ix_handover_counts_business_date'), table_name='handover_counts')
    op.drop_table('handover_counts')
    op.drop_column('wastage_entries', 'decided_at')
    op.drop_column('wastage_entries', 'decided_by')
    op.drop_column('wastage_entries', 'status')
    op.drop_column('shops', 'wastage_approval_paise')
    wastage_status.drop(op.get_bind(), checkfirst=True)
