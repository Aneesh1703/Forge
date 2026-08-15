"""
RepositoryQueryService

Provides repository-level statistics, file dependencies, external library
dependencies, and unresolved relationship diagnostics.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.code_relationship_orm import CodeRelationshipORM
from app.db.models.code_symbol_orm import CodeSymbolORM
from app.db.models.repository_file_orm import RepositoryFileORM
from app.parser.models import SymbolKind
from app.query.graph_query_service import GraphQueryService
from app.query.models import RelationshipEdgeResult, RepositoryStatisticsResult
from app.relationships.models import RelationshipKind, ResolutionStatus
from app.repository.language import Language


class RepositoryQueryService:
    """
    Service for repository-level metrics, diagnostics, and file dependency analysis.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_repository_statistics(self, repo_id: UUID) -> RepositoryStatisticsResult:
        """
        Compute repository metrics (file counts, symbol counts, relationship edge breakdowns).
        """
        # File count & languages
        file_query = (
            select(RepositoryFileORM.language, func.count(RepositoryFileORM.id))
            .where(RepositoryFileORM.repository_id == repo_id)
            .group_by(RepositoryFileORM.language)
        )
        file_res = (await self._session.execute(file_query)).all()
        files_by_lang: dict[Language, int] = {}
        total_files = 0
        for lang_str, count in file_res:
            try:
                lang = Language(lang_str)
            except ValueError:
                lang = Language.PYTHON
            files_by_lang[lang] = count
            total_files += count

        # Symbol count & kinds
        symbol_query = (
            select(CodeSymbolORM.kind, func.count(CodeSymbolORM.id))
            .join(RepositoryFileORM, CodeSymbolORM.file_id == RepositoryFileORM.id)
            .where(RepositoryFileORM.repository_id == repo_id)
            .group_by(CodeSymbolORM.kind)
        )
        sym_res = (await self._session.execute(symbol_query)).all()
        symbols_by_kind: dict[SymbolKind, int] = {}
        total_symbols = 0
        for kind_str, count in sym_res:
            try:
                kind = SymbolKind(kind_str)
            except ValueError:
                kind = SymbolKind.UNKNOWN
            symbols_by_kind[kind] = count
            total_symbols += count

        # Relationship counts by status
        rel_status_query = (
            select(CodeRelationshipORM.status, func.count(CodeRelationshipORM.id))
            .where(CodeRelationshipORM.repository_id == repo_id)
            .group_by(CodeRelationshipORM.status)
        )
        rel_status_res = (await self._session.execute(rel_status_query)).all()
        rels_by_status: dict[ResolutionStatus, int] = {}
        total_relationships = 0
        for status_str, count in rel_status_res:
            try:
                st = ResolutionStatus(status_str)
            except ValueError:
                st = ResolutionStatus.UNRESOLVED
            rels_by_status[st] = count
            total_relationships += count

        # Relationship counts by kind
        rel_kind_query = (
            select(CodeRelationshipORM.kind, func.count(CodeRelationshipORM.id))
            .where(CodeRelationshipORM.repository_id == repo_id)
            .group_by(CodeRelationshipORM.kind)
        )
        rel_kind_res = (await self._session.execute(rel_kind_query)).all()
        rels_by_kind: dict[RelationshipKind, int] = {}
        for kind_str, count in rel_kind_res:
            try:
                rk = RelationshipKind(kind_str)
            except ValueError:
                rk = RelationshipKind.CALLS
            rels_by_kind[rk] = count

        return RepositoryStatisticsResult(
            repository_id=repo_id,
            total_files=total_files,
            total_symbols=total_symbols,
            total_relationships=total_relationships,
            symbols_by_kind=symbols_by_kind,
            files_by_language=files_by_lang,
            relationships_by_status=rels_by_status,
            relationships_by_kind=rels_by_kind,
        )

    async def get_file_dependencies(self, file_id: UUID) -> list[RelationshipEdgeResult]:
        """
        Find all outgoing relationship edges originating from any symbol in file_id.
        """
        query = select(CodeRelationshipORM).where(CodeRelationshipORM.file_id == file_id)
        edges = (await self._session.scalars(query)).all()
        return [GraphQueryService._to_edge_result(edge) for edge in edges]

    async def get_external_dependencies(self, repo_id: UUID) -> list[RelationshipEdgeResult]:
        """
        Find all relationships confirmed to point to external libraries.
        """
        query = select(CodeRelationshipORM).where(
            CodeRelationshipORM.repository_id == repo_id,
            CodeRelationshipORM.status == ResolutionStatus.EXTERNAL.value,
        )
        edges = (await self._session.scalars(query)).all()
        return [GraphQueryService._to_edge_result(edge) for edge in edges]

    async def get_unresolved_relationships(self, repo_id: UUID) -> list[RelationshipEdgeResult]:
        """
        Find all internal relationship edges currently awaiting symbol resolution.
        """
        query = select(CodeRelationshipORM).where(
            CodeRelationshipORM.repository_id == repo_id,
            CodeRelationshipORM.status == ResolutionStatus.UNRESOLVED.value,
        )
        edges = (await self._session.scalars(query)).all()
        return [GraphQueryService._to_edge_result(edge) for edge in edges]
