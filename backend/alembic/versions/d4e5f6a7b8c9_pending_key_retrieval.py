"""pending key retrieval — defer credential to developer

Bearer tokens are no longer minted at approval. Approval provisions only the IAM
identity and lands the key in a 'ready' state; the developer issues (claims) the
credential later. This makes ``credential_id`` nullable, adds ``token_retrieved_at``,
and extends the one-active-key partial unique index to cover 'ready' keys.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('keys', 'credential_id', existing_type=sa.String(255), nullable=True)
    op.add_column(
        'keys',
        sa.Column('token_retrieved_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Recreate the one-active-key partial unique index to also reserve the slot for
    # an approved-but-unclaimed ('ready') key.
    op.drop_index('uq_keys_active_dev_cc', table_name='keys')
    op.create_index(
        'uq_keys_active_dev_cc',
        'keys',
        ['developer_id', 'cost_centre_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'stopped', 'ready')"),
    )


def downgrade() -> None:
    op.drop_index('uq_keys_active_dev_cc', table_name='keys')
    op.create_index(
        'uq_keys_active_dev_cc',
        'keys',
        ['developer_id', 'cost_centre_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'stopped')"),
    )
    op.drop_column('keys', 'token_retrieved_at')
    op.alter_column('keys', 'credential_id', existing_type=sa.String(255), nullable=False)
