"""
CodeSymbolORM

id

file_id

name

kind

signature

return_type

parent_symbol_id

start_line

end_line

start_column

end_column
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.repository_file_orm import RepositoryFileORM


class CodeSymbolORM(Base):
    __tablename__ = "code_symbols"

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

    parent_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("code_symbols.id"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    signature: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    return_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    start_line: Mapped[int] = mapped_column(Integer)

    end_line: Mapped[int] = mapped_column(Integer)

    start_column: Mapped[int] = mapped_column(Integer)

    end_column: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

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
