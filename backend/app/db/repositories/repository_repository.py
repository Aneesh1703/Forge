"""
RepositoryRepository

──────────────────────────────

Constructor

↓

Store AsyncSession

──────────────────────────────

_to_orm(repository)

↓

Repository

↓

RepositoryORM

──────────────────────────────

create(repository)

↓

Convert

↓

add()

↓

flush()

──────────────────────────────

get_by_root_path(root_path)

↓

SELECT *

WHERE root_path = ?

↓

return one / None

──────────────────────────────

update_indexed_at(repository_id, timestamp)

↓

UPDATE repositories

SET indexed_at = ?

WHERE id = ?

──────────────────────────────

delete(repository_id)

↓

DELETE

WHERE id = ?
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepositoryORM
from app.repository.models import Repository


class RepositoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def normalize_git_url(url: str | None) -> str | None:
        if not url or not url.strip():
            return None

        cleaned = url.strip().lower()

        if cleaned.startswith("git@"):
            cleaned = cleaned[4:]
            if ":" in cleaned:
                cleaned = cleaned.replace(":", "/", 1)
        elif "://" in cleaned:
            cleaned = cleaned.split("://", 1)[1]
            if "@" in cleaned:
                cleaned = cleaned.split("@", 1)[1]
            if ":" in cleaned and "/" in cleaned:
                host_port, rest = cleaned.split("/", 1)
                host = host_port.split(":")[0]
                cleaned = f"{host}/{rest}"

        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]

        return cleaned.rstrip("/")

    @staticmethod
    def _to_orm(repository: Repository) -> RepositoryORM:
        normalized = repository.git_url_normalized or RepositoryRepository.normalize_git_url(
            repository.git_url
        )
        root_str = str(repository.root_path.resolve()) if repository.root_path else ""
        return RepositoryORM(
            id=repository.id,
            name=repository.name,
            root_path=root_str,
            git_url=repository.git_url,
            git_url_normalized=normalized,
            default_branch=repository.default_branch,
            indexed_at=repository.indexed_at,
        )

    async def create(self, repository: Repository) -> RepositoryORM:
        orm = self._to_orm(repository)
        self._session.add(orm)
        await self._session.flush()
        return orm

    async def get_by_id(self, repository_id: uuid.UUID) -> RepositoryORM | None:
        result = await self._session.scalars(
            select(RepositoryORM).where(RepositoryORM.id == repository_id)
        )
        return result.one_or_none()

    async def get_by_git_url(self, normalized_url: str) -> RepositoryORM | None:
        result = await self._session.scalars(
            select(RepositoryORM).where(RepositoryORM.git_url_normalized == normalized_url)
        )
        return result.one_or_none()

    async def get_by_root_path(self, root_path: str) -> RepositoryORM | None:
        result = await self._session.scalars(
            select(RepositoryORM).where(RepositoryORM.root_path == root_path)
        )
        return result.one_or_none()

    async def get_existing(self, repository: Repository) -> RepositoryORM | None:
        if repository.id:
            existing = await self.get_by_id(repository.id)
            if existing:
                return existing

        normalized_url = repository.git_url_normalized or self.normalize_git_url(repository.git_url)
        if normalized_url:
            existing = await self.get_by_git_url(normalized_url)
            if existing:
                return existing

        if repository.root_path:
            resolved_path = str(repository.root_path.resolve())
            return await self.get_by_root_path(resolved_path)

        return None

    async def update_indexed_at(self, repository_id: uuid.UUID, timestamp: datetime) -> None:
        await self._session.execute(
            update(RepositoryORM)
            .where(RepositoryORM.id == repository_id)
            .values(indexed_at=timestamp)
        )

    async def delete(self, repository_id: uuid.UUID) -> None:
        await self._session.execute(delete(RepositoryORM).where(RepositoryORM.id == repository_id))
