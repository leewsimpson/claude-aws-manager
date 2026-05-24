"""phase 7 usage snapshots and pricing cache

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pricing_cache',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('model_id', sa.String(length=100), nullable=False),
    sa.Column('model_name', sa.String(length=255), nullable=True),
    sa.Column('input_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('output_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('cache_read_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=True),
    sa.Column('cache_write_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=True),
    sa.Column('region', sa.String(length=50), server_default=sa.text("'ap-southeast-2'"), nullable=False),
    sa.Column('fetched_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_id')
    )
    op.create_table('usage_snapshots',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('key_id', sa.UUID(), nullable=True),
    sa.Column('inference_profile_id', sa.UUID(), nullable=False),
    sa.Column('model_id', sa.String(length=100), nullable=False),
    sa.Column('source', sa.String(length=20), server_default=sa.text("'cloudwatch'"), nullable=False),
    sa.Column('input_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('output_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('cache_read_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('cache_write_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('cost', sa.Numeric(precision=12, scale=4), server_default=sa.text('0.0000'), nullable=False),
    sa.Column('period_start', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('period_end', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('collected_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['inference_profile_id'], ['inference_profiles.id'], ),
    sa.ForeignKeyConstraint(['key_id'], ['keys.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_usage_key_period', 'usage_snapshots', ['key_id', 'period_start'], unique=False)
    op.create_index('idx_usage_profile_period', 'usage_snapshots', ['inference_profile_id', 'period_start'], unique=False)
    op.create_index('idx_usage_collected_at', 'usage_snapshots', ['collected_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_usage_collected_at', table_name='usage_snapshots')
    op.drop_index('idx_usage_profile_period', table_name='usage_snapshots')
    op.drop_index('idx_usage_key_period', table_name='usage_snapshots')
    op.drop_table('usage_snapshots')
    op.drop_table('pricing_cache')
