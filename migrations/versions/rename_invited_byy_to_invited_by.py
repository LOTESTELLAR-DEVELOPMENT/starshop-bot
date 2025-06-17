"""rename invited_byy → invited_by

Revision ID: rename_invited_byy_to_invited_by
Revises: e5793c850b1d          # текущий head‑ID, посмотри `alembic heads`
Create Date: 2025‑06‑15

"""
from alembic import op


# идентификаторы alembic
revision = 'rename_invited_byy_to_invited_by'
down_revision = 'e5793c850b1d'   # поставь реальный head, который показал `alembic heads`
branch_labels = None
depends_on = None


def upgrade():
    # Столбец 'invited_byy' отсутствует, поэтому ничего не делаем
    pass


def downgrade():
    # Столбец 'invited_by' не требуется переименовывать обратно
    pass
