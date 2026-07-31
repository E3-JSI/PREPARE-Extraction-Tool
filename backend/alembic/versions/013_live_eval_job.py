"""liveevaljob: track user-triggered live evaluation runs

Revision ID: 013
Revises: 012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liveevaljob",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("currently_used", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["dataset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["model.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_liveevaljob_dataset_id"), "liveevaljob", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("ix_liveevaljob_model_id"), "liveevaljob", ["model_id"], unique=False
    )
    op.create_index(
        op.f("ix_liveevaljob_status"), "liveevaljob", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_liveevaljob_status"), table_name="liveevaljob")
    op.drop_index(op.f("ix_liveevaljob_model_id"), table_name="liveevaljob")
    op.drop_index(op.f("ix_liveevaljob_dataset_id"), table_name="liveevaljob")
    op.drop_table("liveevaljob")
