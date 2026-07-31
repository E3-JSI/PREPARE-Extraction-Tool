"""add training_run_dataset_link join table for multi-dataset training

Creates the ``training_run_dataset_link`` table (training_run_id, dataset_id,
role) so a run can train on, and optionally evaluate against, several datasets.
Existing single-dataset runs are back-filled with one role='train' link pointing
at their current ``training_run.dataset_id`` (which is kept as the primary
training dataset).

Revision ID: 005
Revises: 004
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'training_run_dataset_link',
        sa.Column('training_run_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(
            ['training_run_id'], ['training_run.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['dataset.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('training_run_id', 'dataset_id', 'role'),
    )

    # Back-fill: every existing run becomes a single-dataset training run.
    op.execute(
        "INSERT INTO training_run_dataset_link "
        "(training_run_id, dataset_id, role) "
        "SELECT id, dataset_id, 'train' FROM training_run"
    )


def downgrade() -> None:
    op.drop_table('training_run_dataset_link')
