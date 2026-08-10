"""
CodeSymbolORM

Represents a parsed code symbol stored in PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.repository_file_orm import RepositoryFileORM


class CodeSymbolORM(Base):
    __tablename__ = "code_symbols"

    # Identity

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    qualified_name: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Hierarchy

    parent_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("code_symbols.id"),
        nullable=True,
    )

    # Location

    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    start_column: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_column: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    start_byte: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_byte: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Semantic information

    return_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    documentation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
    )

    parameters: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    attributes: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    modifiers: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    base_classes: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
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

    file: Mapped["RepositoryFileORM"] = relationship(
        back_populates="symbols",
    )

    parent: Mapped["CodeSymbolORM | None"] = relationship(
        remote_side=[id],
        back_populates="children",
    )

    children: Mapped[list["CodeSymbolORM"]] = relationship(
        back_populates="parent",
    )
