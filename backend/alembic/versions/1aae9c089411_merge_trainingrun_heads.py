"""merge trainingrun heads

Revision ID: 1aae9c089411
Revises: a1b2c3d4e5f6, c1a2b3d4e5f6
Create Date: 2026-05-12 14:49:51.078681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1aae9c089411'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

