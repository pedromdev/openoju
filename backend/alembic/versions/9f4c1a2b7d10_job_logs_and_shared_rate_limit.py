"""job logs in object storage and shared login rate limit

Revision ID: 9f4c1a2b7d10
Revises: 17912db572bd
Create Date: 2026-11-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f4c1a2b7d10'
down_revision: Union[str, Sequence[str], None] = '17912db572bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('jobs', sa.Column('log_key', sa.String(length=2000), nullable=True))
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=300), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_attempts_key', 'login_attempts', ['key'])
    op.create_index('ix_login_attempts_occurred_at', 'login_attempts', ['occurred_at'])
    op.create_index(
        'ix_login_attempts_key_time', 'login_attempts', ['key', 'occurred_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_login_attempts_key_time', table_name='login_attempts')
    op.drop_index('ix_login_attempts_occurred_at', table_name='login_attempts')
    op.drop_index('ix_login_attempts_key', table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_column('jobs', 'log_key')
