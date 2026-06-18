"""merge transaction_history and icu_telemetry heads

Revision ID: 78d4171aff88
Revises: da9b6c1be00c, e8f4a2b1c903
Create Date: 2026-06-17 10:41:12.269745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '78d4171aff88'
down_revision: Union[str, None] = ('da9b6c1be00c', 'e8f4a2b1c903')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
