"""add gliner training fields to trainingrun

Revision ID: a1b2c3d4e5f6
Revises: b6854715f3cd
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b6854715f3cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trainingrun", sa.Column("status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("trainingrun", sa.Column("base_model", sa.String(), nullable=False, server_default=""))
    op.add_column("trainingrun", sa.Column("labels", sa.JSON(), nullable=True))
    op.add_column("trainingrun", sa.Column("output_model_path", sa.String(), nullable=True))
    op.create_index("ix_trainingrun_status", "trainingrun", ["status"])


def downgrade() -> None:
    op.drop_index("ix_trainingrun_status", table_name="trainingrun")
    op.drop_column("trainingrun", "output_model_path")
    op.drop_column("trainingrun", "labels")
    op.drop_column("trainingrun", "base_model")
    op.drop_column("trainingrun", "status")
