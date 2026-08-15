"""
ImpactQueryService

Calculates change impact analysis radii, call path finding,
dependency paths, and circular dependency detection.
"""

from collections import deque
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.code_relationship_orm import CodeRelationshipORM
from app.db.models.code_symbol_orm import CodeSymbolORM
from app.query.graph_query_service import GraphQueryService
from app.query.models import ImpactAnalysisResult, RelationshipEdgeResult, SymbolResult
from app.query.symbol_query_service import SymbolQueryService
from app.relationships.models import RelationshipKind


class ImpactQueryService:
    """
    Service for calculating change impact radius and pathfinding across the code relationship graph.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._symbol_service = SymbolQueryService(session)
        self._graph_service = GraphQueryService(session)

    async def get_impact_analysis(
        self,
        symbol_id: UUID,
        depth: int = 2,
    ) -> ImpactAnalysisResult | None:
        """
        Compute full change impact radius for a target symbol.
        """
        target_sym = await self._symbol_service.find_parent(symbol_id)  # fetch target symbol
        target_orm_query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.id == symbol_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )
        target_orm = await self._session.scalar(target_orm_query)
        if not target_orm:
            return None

        target_sym = SymbolQueryService._to_result(target_orm)

        # 1. Callers (Direct vs Indirect)
        callers_traversal = await self._graph_service.get_callers(symbol_id, depth=depth)
        direct_callers: list[SymbolResult] = []
        indirect_callers: list[SymbolResult] = []

        for edge in callers_traversal.edges:
            if edge.target_symbol_id == symbol_id and edge.source_symbol_id:
                node = callers_traversal.nodes.get(edge.source_symbol_id)
                if node and node not in direct_callers:
                    direct_callers.append(node)

        for node_id, node in callers_traversal.nodes.items():
            if node_id != symbol_id and node not in direct_callers:
                indirect_callers.append(node)

        # 2. Dependent Types (USES_TYPE edges targeting target_symbol)
        type_dep_query = (
            select(CodeRelationshipORM)
            .where(
                CodeRelationshipORM.target_symbol_id == symbol_id,
                CodeRelationshipORM.kind == RelationshipKind.USES_TYPE.value,
            )
            .options(
                selectinload(CodeRelationshipORM.source_symbol).selectinload(CodeSymbolORM.file)
            )
        )
        type_edges = list(await self._session.scalars(type_dep_query))
        dependent_types: list[SymbolResult] = []
        for rel_orm in type_edges:
            if rel_orm.source_symbol:
                dependent_types.append(SymbolQueryService._to_result(rel_orm.source_symbol))

        # 3. Subclasses (INHERITS edges targeting target_symbol)
        subclasses = await self._graph_service.get_descendants(symbol_id, depth=1)

        # 4. Importing Files & Affected File Paths
        importers = await self._graph_service.get_importers(target_sym.file_id)
        importing_file_ids: list[UUID] = list({edge.file_id for edge in importers})

        affected_paths: set[str] = {target_sym.file_path}
        for sym in direct_callers + indirect_callers + dependent_types + subclasses:
            if sym.file_path:
                affected_paths.add(sym.file_path)

        return ImpactAnalysisResult(
            target_symbol=target_sym,
            depth=depth,
            direct_callers=direct_callers,
            indirect_callers=indirect_callers,
            dependent_types=dependent_types,
            subclasses=subclasses,
            importing_file_ids=importing_file_ids,
            affected_file_paths=sorted(list(affected_paths)),
        )

    async def find_call_path(
        self,
        source_symbol_id: UUID,
        target_symbol_id: UUID,
        max_depth: int = 5,
    ) -> list[RelationshipEdgeResult]:
        """
        Find call sequence path from source_symbol_id to target_symbol_id (BFS).
        """
        return await self._find_path(
            source_symbol_id,
            target_symbol_id,
            kind=RelationshipKind.CALLS,
            max_depth=max_depth,
        )

    async def find_dependency_path(
        self,
        source_symbol_id: UUID,
        target_symbol_id: UUID,
        max_depth: int = 5,
    ) -> list[RelationshipEdgeResult]:
        """
        Find general dependency path from source_symbol_id to target_symbol_id
        across any relationship kind (BFS).
        """
        return await self._find_path(
            source_symbol_id,
            target_symbol_id,
            kind=None,
            max_depth=max_depth,
        )

    async def find_circular_dependencies(self, repo_id: UUID) -> list[list[UUID]]:
        """
        Identify circular call/dependency cycles within a repository.
        """
        query = select(CodeRelationshipORM).where(
            CodeRelationshipORM.repository_id == repo_id,
            CodeRelationshipORM.source_symbol_id.is_not(None),
            CodeRelationshipORM.target_symbol_id.is_not(None),
        )
        edges = (await self._session.scalars(query)).all()

        adj: dict[UUID, set[UUID]] = {}
        for edge in edges:
            if edge.source_symbol_id and edge.target_symbol_id:
                adj.setdefault(edge.source_symbol_id, set()).add(edge.target_symbol_id)

        cycles: list[list[UUID]] = []
        visited: set[UUID] = set()
        rec_stack: set[UUID] = set()
        path: list[UUID] = []

        def dfs(node: UUID) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if len(cycle) > 2 and cycle not in cycles:
                        cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for symbol_id in list(adj.keys()):
            if symbol_id not in visited:
                dfs(symbol_id)

        return cycles[:10]  # Return top 10 cycles

    async def _find_path(
        self,
        source_id: UUID,
        target_id: UUID,
        kind: RelationshipKind | None,
        max_depth: int,
    ) -> list[RelationshipEdgeResult]:
        queue: deque[tuple[UUID, list[CodeRelationshipORM]]] = deque([(source_id, [])])
        visited: set[UUID] = {source_id}

        while queue:
            curr_id, path_edges = queue.popleft()
            if curr_id == target_id and path_edges:
                return [GraphQueryService._to_edge_result(e) for e in path_edges]

            if len(path_edges) >= max_depth:
                continue

            query = select(CodeRelationshipORM).where(
                CodeRelationshipORM.source_symbol_id == curr_id
            )
            if kind:
                query = query.where(CodeRelationshipORM.kind == kind.value)

            edges = (await self._session.scalars(query)).all()
            for edge in edges:
                tgt_id = edge.target_symbol_id
                if tgt_id and tgt_id not in visited:
                    visited.add(tgt_id)
                    queue.append((tgt_id, path_edges + [edge]))

        return []
