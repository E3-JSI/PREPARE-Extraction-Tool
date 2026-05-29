"""fix trainingrun missing columns

Revision ID: c1a2b3d4e5f6
Revises: b6854715f3cd
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b6854715f3cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trainingrun', sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='pending'))
    op.add_column('trainingrun', sa.Column('base_model', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
    op.add_column('trainingrun', sa.Column('labels', sa.JSON(), nullable=True))
    op.add_column('trainingrun', sa.Column('output_model_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_trainingrun_status'), 'trainingrun', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trainingrun_status'), table_name='trainingrun')
    op.drop_column('trainingrun', 'output_model_path')
    op.drop_column('trainingrun', 'labels')
    op.drop_column('trainingrun', 'base_model')
    op.drop_column('trainingrun', 'status')
