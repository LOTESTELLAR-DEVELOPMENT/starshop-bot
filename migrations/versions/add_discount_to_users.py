from alembic import op
import sqlalchemy as sa

revision = 'add_discount_to_users'
down_revision = 'a89990086d18'  # замените на актуальный down_revision
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('users', sa.Column('discount', sa.Float, nullable=True))

def downgrade() -> None:
    op.drop_column('users', 'discount') 