"""Add shared validation sets.

Revision ID: 014
Revises: 013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "validation_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "base_model",
            name="uq_validation_set_user_base_model",
        ),
    )

    op.create_table(
        "validation_set_record_link",
        sa.Column("validation_set_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["validation_set_id"],
            ["validation_set.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["record.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("validation_set_id", "record_id"),
    )

    op.add_column(
        "model",
        sa.Column("validation_set_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_model_validation_set_id",
        "model",
        "validation_set",
        ["validation_set_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_model_validation_set_id",
        "model",
        ["validation_set_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_validation_set_id",
        table_name="model",
    )

    op.drop_constraint(
        "fk_model_validation_set_id",
        "model",
        type_="foreignkey",
    )

    op.drop_column("model", "validation_set_id")
    op.drop_table("validation_set_record_link")
    op.drop_table("validation_set")