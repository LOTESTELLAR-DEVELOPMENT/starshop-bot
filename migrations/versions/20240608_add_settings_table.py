"""add settings table for prices

Revision ID: 20240608_add_settings_table
Revises: 
Create Date: 2024-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = '20240608_add_settings_table'
down_revision = 'add_discount_to_users'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'settings',
        sa.Column('key', sa.String(50), primary_key=True),
        sa.Column('value', sa.String(50), nullable=False),
    )
    # Начальные значения
    op.execute("INSERT INTO settings (key, value) VALUES ('star_price', '1.8') ON CONFLICT (key) DO NOTHING;")
    op.execute("INSERT INTO settings (key, value) VALUES ('premium_price_0', '799') ON CONFLICT (key) DO NOTHING;")
    op.execute("INSERT INTO settings (key, value) VALUES ('premium_price_1', '1499') ON CONFLICT (key) DO NOTHING;")
    op.execute("INSERT INTO settings (key, value) VALUES ('premium_price_2', '2499') ON CONFLICT (key) DO NOTHING;")

def downgrade() -> None:
    op.drop_table('settings') 