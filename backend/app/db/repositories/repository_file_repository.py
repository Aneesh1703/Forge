"""
RepositoryFileRepository

──────────────────────────────

Constructor

↓

Store AsyncSession

──────────────────────────────

_to_orm(file)

↓

Convert

RepositoryFile

↓

RepositoryFileORM

──────────────────────────────

bulk_create(files)

↓

if empty

↓

convert every file

↓

add_all()

↓

flush()

──────────────────────────────

get_by_repository(repository_id)

↓

SELECT *

WHERE repository_id = ?

ORDER BY relative_path

↓

return list

──────────────────────────────

get_by_path(repository_id, relative_path)

↓

SELECT *

WHERE repository_id = ?

AND relative_path = ?

↓

return one / None

──────────────────────────────

delete_by_repository(repository_id)

↓

DELETE

WHERE repository_id = ?

──────────────────────────────

delete_by_ids(file_ids)

↓

DELETE

WHERE id IN (...)

"""

import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepositoryFileORM
from app.repository.models import RepositoryFile


class RepositoryFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_orm(file: RepositoryFile) -> RepositoryFileORM:
        return RepositoryFileORM(
            id=file.id,
            repository_id=file.repository_id,
            relative_path=str(file.relative_path),
            absolute_path=str(file.path.resolve()),
            language=file.language.value,
            extension=file.extension,
            size=file.size,
            hash=file.content_hash,
            last_modified=file.last_modified,
        )

    async def bulk_create(
        self,
        files: list[RepositoryFile],
    ) -> None:
        if not files:
            return

        orm_files = [self._to_orm(f) for f in files]

        self._session.add_all(orm_files)
        await self._session.flush()

    async def get_by_repository(
        self,
        repository_id: uuid.UUID,
    ) -> list[RepositoryFileORM]:
        result = await self._session.scalars(
            select(RepositoryFileORM)
            .where(RepositoryFileORM.repository_id == repository_id)
            .order_by(RepositoryFileORM.relative_path)
        )
        return list(result)

    async def get_by_path(
        self,
        repository_id: uuid.UUID,
        relative_path: Path,
    ) -> RepositoryFileORM | None:
        result = await self._session.scalars(
            select(RepositoryFileORM)
            .where(
                RepositoryFileORM.repository_id == repository_id,
                RepositoryFileORM.relative_path == str(relative_path),
            )
            .limit(1)
        )
        return result.one_or_none()

    async def delete_by_repository(
        self,
        repository_id: uuid.UUID,
    ) -> None:
        await self._session.execute(
            delete(RepositoryFileORM).where(RepositoryFileORM.repository_id == repository_id)
        )

    async def delete_by_ids(
        self,
        file_ids: list[uuid.UUID],
    ) -> None:
        if not file_ids:
            return

        await self._session.execute(
            delete(RepositoryFileORM).where(RepositoryFileORM.id.in_(file_ids))
        )
