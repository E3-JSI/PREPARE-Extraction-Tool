"""clusterjob: track "cluster all labels" batch runs

Revision ID: 012
Revises: 011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clusterjob",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("clustered_labels", sa.JSON(), nullable=False),
        sa.Column("skipped_labels", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("currently_used", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["dataset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clusterjob_dataset_id"), "clusterjob", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("ix_clusterjob_status"), "clusterjob", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_clusterjob_status"), table_name="clusterjob")
    op.drop_index(op.f("ix_clusterjob_dataset_id"), table_name="clusterjob")
    op.drop_table("clusterjob")
