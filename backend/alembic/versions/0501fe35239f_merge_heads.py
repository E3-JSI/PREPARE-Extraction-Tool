"""merge heads

Revision ID: 0501fe35239f
Revises: 002, b8f3b190ffa4
Create Date: 2026-06-16 23:28:54.790007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0501fe35239f'
down_revision: Union[str, None] = ('002', 'b8f3b190ffa4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

