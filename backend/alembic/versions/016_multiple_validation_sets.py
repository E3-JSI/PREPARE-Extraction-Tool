"""Allow multiple validation sets per base model.

Revision ID: 016
Revises: 015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ix_validation_set_user_base_model_created_at_id"


def upgrade() -> None:
    op.drop_constraint(
        "uq_validation_set_user_base_model",
        "validation_set",
        type_="unique",
    )

    op.create_index(
        INDEX_NAME,
        "validation_set",
        ["user_id", "base_model", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate_group = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM validation_set
            GROUP BY user_id, base_model
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()

    if duplicate_group is not None:
        raise RuntimeError(
            "Cannot downgrade revision 016 because multiple validation sets "
            "exist for at least one user and base model."
        )

    op.drop_index(
        INDEX_NAME,
        table_name="validation_set",
    )

    op.create_unique_constraint(
        "uq_validation_set_user_base_model",
        "validation_set",
        ["user_id", "base_model"],
    )