"""
GraphQueryService

Executes graph relationship traversals (callers, callees, inheritance,
dependencies, module imports/importers).
"""

from collections import deque
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.code_relationship_orm import CodeRelationshipORM
from app.db.models.code_symbol_orm import CodeSymbolORM
from app.query.models import GraphTraversalResult, RelationshipEdgeResult, SymbolResult
from app.query.symbol_query_service import SymbolQueryService
from app.relationships.models import RelationshipKind, ResolutionStatus


class GraphQueryService:
    """
    Service for querying the code relationship graph.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._symbol_service = SymbolQueryService(session)

    @staticmethod
    def _to_edge_result(orm: CodeRelationshipORM) -> RelationshipEdgeResult:
        try:
            kind = RelationshipKind(orm.kind)
        except ValueError:
            kind = RelationshipKind.CALLS

        try:
            status = ResolutionStatus(orm.status)
        except ValueError:
            status = ResolutionStatus.UNRESOLVED

        return RelationshipEdgeResult(
            id=orm.id,
            repository_id=orm.repository_id,
            file_id=orm.file_id,
            kind=kind,
            status=status,
            target_name=orm.target_name,
            source_symbol_id=orm.source_symbol_id,
            source_scope=orm.source_scope,
            source_qualified_name=orm.source_qualified_name,
            source_line=orm.source_line,
            source_column=orm.source_column,
            target_symbol_id=orm.target_symbol_id,
            target_module_hint=orm.target_module_hint,
            metadata=orm.metadata_json or {},
        )

    async def get_callers(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> GraphTraversalResult:
        """
        Find functions/methods that call target symbol_id (incoming CALLS edges).
        Supports multi-hop traversal up to `depth`.
        """
        depth = max(1, min(depth, 5))
        result = GraphTraversalResult(root_symbol_id=symbol_id, max_depth=depth)

        visited_symbols: set[UUID] = {symbol_id}
        queue: deque[tuple[UUID, int]] = deque([(symbol_id, 0)])

        root_sym = await self._get_symbol_by_id(symbol_id)
        if root_sym:
            result.nodes[symbol_id] = root_sym

        while queue:
            curr_id, curr_depth = queue.popleft()
            if curr_depth >= depth:
                continue

            query = (
                select(CodeRelationshipORM)
                .where(
                    CodeRelationshipORM.target_symbol_id == curr_id,
                    CodeRelationshipORM.kind == RelationshipKind.CALLS.value,
                )
                .options(
                    selectinload(CodeRelationshipORM.source_symbol).selectinload(CodeSymbolORM.file)
                )
            )
            edges_orm = (await self._session.scalars(query)).all()

            for edge in edges_orm:
                edge_res = self._to_edge_result(edge)
                result.edges.append(edge_res)

                if edge.source_symbol_id and edge.source_symbol:
                    src_id = edge.source_symbol_id
                    if src_id not in result.nodes:
                        result.nodes[src_id] = SymbolQueryService._to_result(edge.source_symbol)

                    if src_id not in visited_symbols:
                        visited_symbols.add(src_id)
                        queue.append((src_id, curr_depth + 1))

        return result

    async def get_callees(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> GraphTraversalResult:
        """
        Find functions/methods called by symbol_id (outgoing CALLS edges).
        Supports multi-hop traversal up to `depth`.
        """
        depth = max(1, min(depth, 5))
        result = GraphTraversalResult(root_symbol_id=symbol_id, max_depth=depth)

        visited_symbols: set[UUID] = {symbol_id}
        queue: deque[tuple[UUID, int]] = deque([(symbol_id, 0)])

        root_sym = await self._get_symbol_by_id(symbol_id)
        if root_sym:
            result.nodes[symbol_id] = root_sym

        while queue:
            curr_id, curr_depth = queue.popleft()
            if curr_depth >= depth:
                continue

            query = (
                select(CodeRelationshipORM)
                .where(
                    CodeRelationshipORM.source_symbol_id == curr_id,
                    CodeRelationshipORM.kind == RelationshipKind.CALLS.value,
                )
                .options(
                    selectinload(CodeRelationshipORM.target_symbol).selectinload(CodeSymbolORM.file)
                )
            )
            edges_orm = (await self._session.scalars(query)).all()

            for edge in edges_orm:
                edge_res = self._to_edge_result(edge)
                result.edges.append(edge_res)

                if edge.target_symbol_id and edge.target_symbol:
                    tgt_id = edge.target_symbol_id
                    if tgt_id not in result.nodes:
                        result.nodes[tgt_id] = SymbolQueryService._to_result(edge.target_symbol)

                    if tgt_id not in visited_symbols:
                        visited_symbols.add(tgt_id)
                        queue.append((tgt_id, curr_depth + 1))

        return result

    async def get_ancestors(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> list[SymbolResult]:
        """
        Find superclasses / base classes of class symbol_id (outgoing INHERITS edges).
        """
        query = (
            select(CodeRelationshipORM)
            .where(
                CodeRelationshipORM.source_symbol_id == symbol_id,
                CodeRelationshipORM.kind == RelationshipKind.INHERITS.value,
            )
            .options(
                selectinload(CodeRelationshipORM.target_symbol).selectinload(CodeSymbolORM.file)
            )
        )
        edges = (await self._session.scalars(query)).all()
        ancestors: list[SymbolResult] = []
        for edge in edges:
            if edge.target_symbol:
                ancestors.append(SymbolQueryService._to_result(edge.target_symbol))
        return ancestors

    async def get_descendants(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> list[SymbolResult]:
        """
        Find subclasses of class symbol_id (incoming INHERITS edges).
        """
        query = (
            select(CodeRelationshipORM)
            .where(
                CodeRelationshipORM.target_symbol_id == symbol_id,
                CodeRelationshipORM.kind == RelationshipKind.INHERITS.value,
            )
            .options(
                selectinload(CodeRelationshipORM.source_symbol).selectinload(CodeSymbolORM.file)
            )
        )
        edges = (await self._session.scalars(query)).all()
        descendants: list[SymbolResult] = []
        for edge in edges:
            if edge.source_symbol:
                descendants.append(SymbolQueryService._to_result(edge.source_symbol))
        return descendants

    async def get_dependencies(
        self,
        symbol_id: UUID,
    ) -> list[RelationshipEdgeResult]:
        """
        Find all outgoing relationship edges from symbol_id.
        """
        query = select(CodeRelationshipORM).where(CodeRelationshipORM.source_symbol_id == symbol_id)
        edges = (await self._session.scalars(query)).all()
        return [self._to_edge_result(edge) for edge in edges]

    async def get_dependents(
        self,
        symbol_id: UUID,
    ) -> list[RelationshipEdgeResult]:
        """
        Find all incoming relationship edges pointing to symbol_id.
        """
        query = select(CodeRelationshipORM).where(CodeRelationshipORM.target_symbol_id == symbol_id)
        edges = (await self._session.scalars(query)).all()
        return [self._to_edge_result(edge) for edge in edges]

    async def get_imports(
        self,
        file_id: UUID,
    ) -> list[RelationshipEdgeResult]:
        """
        Find all module import relationships declared in a file.
        """
        query = select(CodeRelationshipORM).where(
            CodeRelationshipORM.file_id == file_id,
            CodeRelationshipORM.kind == RelationshipKind.IMPORTS.value,
        )
        edges = (await self._session.scalars(query)).all()
        return [self._to_edge_result(edge) for edge in edges]

    async def get_importers(
        self,
        file_id: UUID,
    ) -> list[RelationshipEdgeResult]:
        """
        Find all files that import symbols/modules from target file_id.
        """
        sym_query = select(CodeSymbolORM.id).where(CodeSymbolORM.file_id == file_id)
        sym_ids = (await self._session.scalars(sym_query)).all()
        if not sym_ids:
            return []

        query = select(CodeRelationshipORM).where(
            CodeRelationshipORM.target_symbol_id.in_(sym_ids),
            CodeRelationshipORM.kind == RelationshipKind.IMPORTS.value,
        )
        edges = (await self._session.scalars(query)).all()
        return [self._to_edge_result(edge) for edge in edges]

    async def _get_symbol_by_id(self, symbol_id: UUID) -> SymbolResult | None:
        query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.id == symbol_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )
        sym_orm = await self._session.scalar(query)
        return SymbolQueryService._to_result(sym_orm) if sym_orm else None
