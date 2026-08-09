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
    def _to_orm(repository: Repository) -> RepositoryORM:
        return RepositoryORM(
            id=repository.id,
            name=repository.name,
            root_path=str(repository.root_path),
            indexed_at=repository.indexed_at,
        )

    async def create(self, repository: Repository) -> RepositoryORM:
        orm = self._to_orm(repository)
        self._session.add(orm)
        await self._session.flush()
        return orm

    async def get_by_root_path(self, root_path: str) -> RepositoryORM | None:
        result = await self._session.scalars(
            select(RepositoryORM).where(RepositoryORM.root_path == root_path)
        )
        return result.one_or_none()

    async def update_indexed_at(self, repository_id: uuid.UUID, timestamp: datetime) -> None:
        await self._session.execute(
            update(RepositoryORM)
            .where(RepositoryORM.id == repository_id)
            .values(indexed_at=timestamp)
        )

    async def delete(self, repository_id: uuid.UUID) -> None:
        await self._session.execute(delete(RepositoryORM).where(RepositoryORM.id == repository_id))
