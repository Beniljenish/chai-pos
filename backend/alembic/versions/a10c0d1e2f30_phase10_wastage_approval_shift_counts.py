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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wastage_entries', 'decided_at')
    op.drop_column('wastage_entries', 'decided_by')
    op.drop_column('wastage_entries', 'status')
    op.drop_column('shops', 'wastage_approval_paise')
    wastage_status.drop(op.get_bind(), checkfirst=True)
