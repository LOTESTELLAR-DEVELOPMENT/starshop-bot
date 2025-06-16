"""merge all heads

Revision ID: 5652b5769fcd
Revises: 20240608_add_settings_table, a89990086d18, add_discount_to_users
Create Date: 2025-05-28 00:53:42.064236

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5652b5769fcd'
down_revision: Union[str, None] = ('20240608_add_settings_table', 'a89990086d18', 'add_discount_to_users')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
