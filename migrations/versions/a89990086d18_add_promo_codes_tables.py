"""add promo codes tables

Revision ID: a89990086d18
Revises: 5e0920b3da6f
Create Date: 2025-05-27 17:58:32.198456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a89990086d18'
down_revision: Union[str, None] = '5e0920b3da6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'promo_codes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('code', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('promo_type', sa.String(20), nullable=False, default='balance'),
        sa.Column('value', sa.Float, nullable=False),
        sa.Column('max_uses', sa.Integer, nullable=True),
        sa.Column('current_uses', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('meta', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        'promo_history',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('promo_code_id', sa.Integer, sa.ForeignKey('promo_codes.id'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('promo_history')
    op.drop_table('promo_codes')
