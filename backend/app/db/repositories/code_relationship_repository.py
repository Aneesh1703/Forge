"""
Repository for persisting and querying code relationships.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeRelationshipORM
from app.relationships.models import CodeRelationship


class CodeRelationshipRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _to_orm(rel: CodeRelationship) -> CodeRelationshipORM:
        return CodeRelationshipORM(
            id=rel.id,
            repository_id=rel.repository_id,
            file_id=rel.file_id,
            source_symbol_id=rel.source_symbol_id,
            source_scope=rel.source_scope[:256] if rel.source_scope else None,
            source_qualified_name=rel.source_qualified_name[:512]
            if rel.source_qualified_name
            else None,
            source_line=rel.source_line,
            source_column=rel.source_column,
            target_symbol_id=rel.target_symbol_id,
            target_name=rel.target_name[:512],
            target_module_hint=rel.target_module_hint[:512] if rel.target_module_hint else None,
            kind=rel.kind.value,
            status=rel.status.value,
            metadata_json=rel.metadata,
        )

    async def bulk_create(
        self,
        relationships: list[CodeRelationship],
    ) -> None:
        if not relationships:
            return

        orm_relationships = [self._to_orm(rel) for rel in relationships]
        self._session.add_all(orm_relationships)
        await self._session.flush()

    async def delete_by_file_ids(
        self,
        file_ids: list[UUID],
    ) -> None:
        if not file_ids:
            return

        await self._session.execute(
            delete(CodeRelationshipORM).where(CodeRelationshipORM.file_id.in_(file_ids))
        )

    async def get_by_repository(
        self,
        repository_id: UUID,
    ) -> list[CodeRelationshipORM]:
        result = await self._session.scalars(
            select(CodeRelationshipORM).where(CodeRelationshipORM.repository_id == repository_id)
        )
        return list(result)

    async def get_unresolved_by_target_names(
        self,
        repository_id: UUID,
        target_names: list[str],
    ) -> list[CodeRelationshipORM]:
        if not target_names:
            return []

        result = await self._session.scalars(
            select(CodeRelationshipORM).where(
                CodeRelationshipORM.repository_id == repository_id,
                CodeRelationshipORM.status == "unresolved",
                CodeRelationshipORM.target_name.in_(target_names),
            )
        )
        return list(result)

    async def get_outgoing_relationships(
        self,
        file_id: UUID,
    ) -> list[CodeRelationshipORM]:
        result = await self._session.scalars(
            select(CodeRelationshipORM).where(CodeRelationshipORM.file_id == file_id)
        )
        return list(result)

    async def get_incoming_relationships(
        self,
        symbol_id: UUID,
    ) -> list[CodeRelationshipORM]:
        result = await self._session.scalars(
            select(CodeRelationshipORM).where(CodeRelationshipORM.target_symbol_id == symbol_id)
        )
        return list(result)
