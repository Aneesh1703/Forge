"""Initial schema

Revision ID: c9da52ce33b9
Revises:
Create Date: 2026-08-02 22:54:44.781997
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9da52ce33b9"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ------------------------------------------------------------------
    # repositories
    # ------------------------------------------------------------------

    op.create_table(
        "repositories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=False),
        sa.Column("git_url", sa.String(length=1024), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "root_path",
            name="uq_repositories_root_path",
        ),
    )

    op.create_index(
        "ix_repositories_root_path",
        "repositories",
        ["root_path"],
    )

    # ------------------------------------------------------------------
    # repository_files
    # ------------------------------------------------------------------

    op.create_table(
        "repository_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("absolute_path", sa.String(length=2048), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "relative_path",
            name="uq_repository_files_repo_path",
        ),
    )

    op.create_index(
        "ix_repository_files_repository_id",
        "repository_files",
        ["repository_id"],
    )

    op.create_index(
        "ix_repository_files_language",
        "repository_files",
        ["language"],
    )

    op.create_index(
        "ix_repository_files_content_hash",
        "repository_files",
        ["content_hash"],
    )

    # ------------------------------------------------------------------
    # code_symbols
    # ------------------------------------------------------------------

    op.create_table(
        "code_symbols",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("parent_symbol_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("return_type", sa.String(length=255), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("start_column", sa.Integer(), nullable=False),
        sa.Column("end_column", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["repository_files.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_symbol_id"],
            ["code_symbols.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_code_symbols_file_id",
        "code_symbols",
        ["file_id"],
    )

    op.create_index(
        "ix_code_symbols_kind",
        "code_symbols",
        ["kind"],
    )

    op.create_index(
        "ix_code_symbols_parent_symbol_id",
        "code_symbols",
        ["parent_symbol_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""

    # ------------------------------------------------------------------
    # code_symbols
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_code_symbols_parent_symbol_id",
        table_name="code_symbols",
    )

    op.drop_index(
        "ix_code_symbols_kind",
        table_name="code_symbols",
    )

    op.drop_index(
        "ix_code_symbols_file_id",
        table_name="code_symbols",
    )

    op.drop_table("code_symbols")

    # ------------------------------------------------------------------
    # repository_files
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_repository_files_content_hash",
        table_name="repository_files",
    )

    op.drop_index(
        "ix_repository_files_language",
        table_name="repository_files",
    )

    op.drop_index(
        "ix_repository_files_repository_id",
        table_name="repository_files",
    )

    op.drop_table("repository_files")

    # ------------------------------------------------------------------
    # repositories
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_repositories_root_path",
        table_name="repositories",
    )

    op.drop_table("repositories")
