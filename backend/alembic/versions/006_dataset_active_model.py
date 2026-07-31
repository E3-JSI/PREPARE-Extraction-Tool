"""add active_model_id to dataset for NER model selection

Adds a nullable ``dataset.active_model_id`` FK -> ``model.id`` (ON DELETE SET
NULL) recording which trained model a dataset uses for NER extraction. A null
value means the bioner default model is used.

Revision ID: 006
Revises: 005
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dataset', sa.Column('active_model_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_dataset_active_model_id',
        'dataset',
        'model',
        ['active_model_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_dataset_active_model_id', 'dataset', type_='foreignkey')
    op.drop_column('dataset', 'active_model_id')
