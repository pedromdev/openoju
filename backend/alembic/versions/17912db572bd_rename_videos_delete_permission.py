"""rename videos delete permission

Revision ID: 17912db572bd
Revises: d3b665298713
Create Date: 2026-11-14 17:51:31.398531
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '17912db572bd'
down_revision: Union[str, Sequence[str], None] = 'd3b665298713'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE permission_groups
               SET permissions = replace(
                     permissions::text, '"videos.delete"', '"videos.manage"'
                   )::json
            """
        )
    else:
        op.execute(
            """
            UPDATE permission_groups
               SET permissions = replace(
                     permissions, '"videos.delete"', '"videos.manage"'
                   )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE permission_groups
               SET permissions = replace(
                     permissions::text, '"videos.manage"', '"videos.delete"'
                   )::json
            """
        )
    else:
        op.execute(
            """
            UPDATE permission_groups
               SET permissions = replace(
                     permissions, '"videos.manage"', '"videos.delete"'
                   )
            """
        )
