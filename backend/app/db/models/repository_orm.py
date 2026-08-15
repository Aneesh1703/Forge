"""
RepositoryORM

id

name

root_path

git_url

default_branch

indexed_at

created_at
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.models.base import Base

if TYPE_CHECKING:
    from app.db.models.repository_file_orm import RepositoryFileORM


class RepositoryORM(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    git_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    git_url_normalized: Mapped[str | None] = mapped_column(
        String(1024),
        unique=True,
        nullable=True,
    )

    default_branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    files: Mapped[list["RepositoryFileORM"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )
