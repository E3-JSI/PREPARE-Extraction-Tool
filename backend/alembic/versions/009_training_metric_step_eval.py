"""training_metric: add step + eval_loss

Revision ID: 009
Revises: 008
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_metric", sa.Column("step", sa.Integer(), nullable=True))
    op.add_column("training_metric", sa.Column("eval_loss", sa.Float(), nullable=True))
    op.create_index("ix_training_metric_step", "training_metric", ["step"])


def downgrade() -> None:
    op.drop_index("ix_training_metric_step", table_name="training_metric")
    op.drop_column("training_metric", "eval_loss")
    op.drop_column("training_metric", "step")
