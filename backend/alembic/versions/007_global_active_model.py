"""global active model: add app_settings, drop dataset.active_model_id

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active_model_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["active_model_id"], ["model.id"], ondelete="SET NULL"),
    )
    # Seed the singleton row.
    op.execute("INSERT INTO app_settings (id, active_model_id) VALUES (1, NULL)")
    # Drop the per-dataset active model column (FK constraint first — named in 006).
    op.drop_constraint("fk_dataset_active_model_id", "dataset", type_="foreignkey")
    with op.batch_alter_table("dataset") as batch:
        batch.drop_column("active_model_id")


def downgrade() -> None:
    op.add_column(
        "dataset",
        sa.Column("active_model_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dataset_active_model_id",
        "dataset",
        "model",
        ["active_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_table("app_settings")
