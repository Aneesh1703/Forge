"""add rich code symbol metadata

Revision ID: 4e5babf706f1
Revises: c9da52ce33b9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4e5babf706f1"
down_revision: Union[str, Sequence[str], None] = "c9da52ce33b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column(
        "code_symbols",
        "signature",
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "qualified_name",
            sa.String(length=512),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "documentation",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "visibility",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "modifiers",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "base_classes",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.add_column(
        "code_symbols",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    # Only needed while migrating existing rows.
    op.alter_column(
        "code_symbols",
        "visibility",
        server_default=None,
    )


def downgrade() -> None:
    op.add_column(
        "code_symbols",
        sa.Column(
            "signature",
            sa.Text(),
            nullable=True,
        ),
    )

    op.drop_column("code_symbols", "metadata_json")
    op.drop_column("code_symbols", "base_classes")
    op.drop_column("code_symbols", "modifiers")
    op.drop_column("code_symbols", "attributes")
    op.drop_column("code_symbols", "parameters")
    op.drop_column("code_symbols", "visibility")
    op.drop_column("code_symbols", "documentation")
    op.drop_column("code_symbols", "qualified_name")
