"""phase 5 inference profiles

Revision ID: a1b2c3d4e5f6
Revises: 57f0fe8dd206
Create Date: 2026-05-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '57f0fe8dd206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('inference_profiles',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('cost_centre_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.String(length=100), nullable=False),
    sa.Column('profile_arn', sa.String(length=500), nullable=False),
    sa.Column('profile_name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cost_centre_id'], ['cost_centres.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile_arn')
    )
    op.create_index(
        'uq_inference_profiles_cc_model',
        'inference_profiles',
        ['cost_centre_id', 'model_id'],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_inference_profiles_cc_model',
        table_name='inference_profiles',
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table('inference_profiles')
