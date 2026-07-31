"""mapping job: track progress for auto-map-all runs

Revision ID: 011
Revises: 010
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mappingjob",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("mapped_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["dataset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mappingjob_dataset_id"),
        "mappingjob",
        ["dataset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mappingjob_status"), "mappingjob", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mappingjob_status"), table_name="mappingjob")
    op.drop_index(op.f("ix_mappingjob_dataset_id"), table_name="mappingjob")
    op.drop_table("mappingjob")
