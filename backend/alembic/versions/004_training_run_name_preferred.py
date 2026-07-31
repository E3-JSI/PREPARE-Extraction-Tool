"""add name and preferred columns to training_run

Revision ID: 004
Revises: 003
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'training_run',
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        'training_run',
        sa.Column(
            'preferred',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('training_run', 'preferred')
    op.drop_column('training_run', 'name')
