"""
RepositoryContextBuilder

Assembles 360-degree structural context bundles for AI prompt consumption and semantic retrieval.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.code_symbol_orm import CodeSymbolORM
from app.query.graph_query_service import GraphQueryService
from app.query.models import (
    RelationshipEdgeResult,
    RepositoryContext,
    SymbolQueryFilter,
    SymbolResult,
)
from app.query.symbol_query_service import SymbolQueryService


class RepositoryContextBuilder:
    """
    Builder for assembling unified structural context around symbols or search terms.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._symbol_service = SymbolQueryService(session)
        self._graph_service = GraphQueryService(session)

    async def get_related_symbols(
        self,
        symbol_id: UUID,
        depth: int = 1,
    ) -> list[SymbolResult]:
        """
        Unified helper aggregating parent, children, callers, callees,
        ancestors, descendants, and dependencies.
        """
        related_map: dict[UUID, SymbolResult] = {}

        # 1. Parent symbol
        parent_sym = await self._symbol_service.find_parent(symbol_id)
        if parent_sym and parent_sym.id != symbol_id:
            related_map[parent_sym.id] = parent_sym

        # 2. Direct children
        children = await self._symbol_service.find_children(symbol_id)
        for child in children:
            if child.id != symbol_id:
                related_map[child.id] = child

        # 3. Callers & Callees
        callers = await self._graph_service.get_callers(symbol_id, depth=depth)
        for node_id, node in callers.nodes.items():
            if node_id != symbol_id:
                related_map[node_id] = node

        callees = await self._graph_service.get_callees(symbol_id, depth=depth)
        for node_id, node in callees.nodes.items():
            if node_id != symbol_id:
                related_map[node_id] = node

        # 4. Ancestors & Descendants
        ancestors = await self._graph_service.get_ancestors(symbol_id, depth=depth)
        for anc in ancestors:
            if anc.id != symbol_id:
                related_map[anc.id] = anc

        descendants = await self._graph_service.get_descendants(symbol_id, depth=depth)
        for desc in descendants:
            if desc.id != symbol_id:
                related_map[desc.id] = desc

        return list(related_map.values())

    async def build_symbol_context(
        self,
        repo_id: UUID,
        symbol_id: UUID,
        depth: int = 1,
    ) -> RepositoryContext | None:
        """
        Assemble complete 360-degree RepositoryContext around a target symbol.
        """
        target_orm_query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.id == symbol_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )
        target_orm = await self._session.scalar(target_orm_query)
        if not target_orm:
            return None

        primary_sym = SymbolQueryService._to_result(target_orm)
        related_syms = await self.get_related_symbols(symbol_id, depth=depth)

        # Collect outgoing & incoming relationship edges
        deps = await self._graph_service.get_dependencies(symbol_id)
        dependents = await self._graph_service.get_dependents(symbol_id)
        edges: list[RelationshipEdgeResult] = list({e.id: e for e in deps + dependents}.values())

        # Relevant file paths
        files: set[str] = {primary_sym.file_path}
        for rel in related_syms:
            if rel.file_path:
                files.add(rel.file_path)

        return RepositoryContext(
            repository_id=repo_id,
            primary_symbols=[primary_sym],
            related_symbols=related_syms,
            relationships=edges,
            relevant_files=sorted(list(files)),
            metadata={
                "target_symbol_id": str(symbol_id),
                "related_count": len(related_syms),
                "relationship_count": len(edges),
            },
        )

    async def build_query_context(
        self,
        repo_id: UUID,
        query_term: str,
        max_symbols: int = 5,
    ) -> RepositoryContext:
        """
        Assemble RepositoryContext for a text query search.
        """
        filter_opts = SymbolQueryFilter(repo_id=repo_id, name_prefix=query_term, limit=max_symbols)
        primary_syms = await self._symbol_service.search_symbols(repo_id, filter_opts)

        if not primary_syms:
            # Fallback to substring query on qualified_name
            filter_opts_qual = SymbolQueryFilter(
                repo_id=repo_id, qualified_name_prefix=query_term, limit=max_symbols
            )
            primary_syms = await self._symbol_service.search_symbols(repo_id, filter_opts_qual)

        related_map: dict[UUID, SymbolResult] = {}
        all_edges: dict[UUID, RelationshipEdgeResult] = {}
        relevant_files: set[str] = set()

        for prim in primary_syms:
            if prim.file_path:
                relevant_files.add(prim.file_path)

            rel_list = await self.get_related_symbols(prim.id, depth=1)
            for r in rel_list:
                if r.id not in [p.id for p in primary_syms]:
                    related_map[r.id] = r
                if r.file_path:
                    relevant_files.add(r.file_path)

            deps = await self._graph_service.get_dependencies(prim.id)
            for d in deps:
                all_edges[d.id] = d

        return RepositoryContext(
            repository_id=repo_id,
            primary_symbols=primary_syms,
            related_symbols=list(related_map.values()),
            relationships=list(all_edges.values()),
            relevant_files=sorted(list(relevant_files)),
            metadata={
                "query_term": query_term,
                "primary_count": len(primary_syms),
                "related_count": len(related_map),
            },
        )
