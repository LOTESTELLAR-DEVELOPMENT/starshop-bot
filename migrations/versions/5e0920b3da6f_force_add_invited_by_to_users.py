"""force add invited_by to users

Revision ID: 5e0920b3da6f
Revises: e4f337a1c60e
Create Date: 2024-06-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e0920b3da6f'
down_revision = 'e4f337a1c60e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('invited_by', sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column('users', 'invited_by')
