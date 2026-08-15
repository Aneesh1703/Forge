"""
CodeRelationshipORM

Represents a directed relationship between code symbols or modules stored in PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.code_symbol_orm import CodeSymbolORM
    from app.db.models.repository_file_orm import RepositoryFileORM
    from app.db.models.repository_orm import RepositoryORM


class CodeRelationshipORM(Base):
    __tablename__ = "code_relationships"

    __table_args__ = (
        Index("ix_code_relationships_source_symbol_kind", "source_symbol_id", "kind"),
        Index("ix_code_relationships_target_symbol_kind", "target_symbol_id", "kind"),
        Index("ix_code_relationships_repo_status", "repository_id", "status"),
        Index("ix_code_relationships_repo_file_line", "repository_id", "file_id", "source_line"),
    )

    # Identity

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Source details

    source_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("code_symbols.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    source_scope: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    source_qualified_name: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    source_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    source_column: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Target details

    target_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("code_symbols.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    target_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    target_module_hint: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    # Classification & Status

    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unresolved",
    )

    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Timestamps

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships

    repository: Mapped["RepositoryORM"] = relationship()

    file: Mapped["RepositoryFileORM"] = relationship()

    source_symbol: Mapped["CodeSymbolORM | None"] = relationship(
        foreign_keys=[source_symbol_id],
    )

    target_symbol: Mapped["CodeSymbolORM | None"] = relationship(
        foreign_keys=[target_symbol_id],
    )
