"""add payments table

Revision ID: 4e420cf628b5
Revises: 5e0920b3da6f
Create Date: 2025-05-25 00:39:29.155366

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e420cf628b5'
down_revision: Union[str, None] = '20240608_add_settings_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('uuid', sa.String(64), unique=True, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('is_paid', sa.Boolean, server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.text('now()'), nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payments')
