"""model: add source + engine columns for model discovery

Revision ID: 010
Revises: 009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model", sa.Column("source", sa.String(), nullable=True))
    op.add_column("model", sa.Column("engine", sa.String(), nullable=True))

    # Backfill existing rows. Order matters: trained-run rows first, then
    # baseline anchors, then everything else by whether it has an artifact path.
    op.execute(
        """
        UPDATE model SET source = 'trained', engine = 'gliner'
        WHERE id IN (SELECT model_id FROM training_run WHERE model_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE model SET source = 'baseline', engine = NULL
        WHERE source IS NULL AND (name = 'Base model' OR path IS NULL)
        """
    )
    op.execute(
        """
        UPDATE model
        SET source = CASE WHEN path IS NOT NULL THEN 'trained' ELSE 'baseline' END
        WHERE source IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("model", "engine")
    op.drop_column("model", "source")
