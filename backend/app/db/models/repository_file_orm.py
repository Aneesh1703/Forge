"""
RepositoryFileORM

id

repository_id

relative_path

absolute_path

language

extension

size

hash

last_modified
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.code_symbol_orm import CodeSymbolORM
    from app.db.models.repository_orm import RepositoryORM


class RepositoryFileORM(Base):
    __tablename__ = "repository_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id"),
        nullable=False,
    )

    relative_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )

    absolute_path: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )

    language: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    extension: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    last_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    repository: Mapped["RepositoryORM"] = relationship(
        back_populates="files",
    )

    symbols: Mapped[list["CodeSymbolORM"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
    )
