"""add payment_settings table

Revision ID: e5793c850b1d
Revises: 5652b5769fcd
Create Date: 2025-05-28 00:53:50.899695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5793c850b1d'
down_revision: Union[str, None] = '4e420cf628b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'payment_settings',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('system', sa.Text, nullable=False, unique=True),
        sa.Column('min_amount', sa.Numeric, nullable=False, server_default='10'),
        sa.Column('currency', sa.Text, nullable=False),
        sa.Column('exchange_rate', sa.Numeric),
        sa.Column('updated_at', sa.TIMESTAMP, server_default=sa.func.now())
    )
    op.execute(
        "INSERT INTO payment_settings (system, min_amount, currency, exchange_rate) VALUES "
        "('sbp', 10, 'RUB', NULL),"
        "('crypto', 75, 'RUB', 75)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
