"""
Graph + Vector Hybrid Context Builder

Fuses semantic vector similarity search results with AST graph structural relationships
(callers, callees, inheritance, module imports), query understanding intent parsing,
and hybrid score re-ranking to generate rich AI prompt context.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.query.context_builder import RepositoryContextBuilder
from app.query.models import SymbolQueryFilter, SymbolResult
from app.query.symbol_query_service import SymbolQueryService
from app.retrieval.models import (
    HybridContextBundle,
    HybridContextRequest,
    SemanticSearchRequest,
)
from app.retrieval.query_understanding import QueryUnderstandingEngine
from app.retrieval.reranker import HybridReRanker
from app.retrieval.semantic_retriever import SemanticRetriever

logger = logging.getLogger(__name__)


class HybridContextBuilder:
    """
    7-Stage Builder engine for fusing semantic retrieval with graph structural intelligence.
    """

    def __init__(
        self,
        retriever: SemanticRetriever,
        session: AsyncSession | None = None,
        query_engine: QueryUnderstandingEngine | None = None,
        reranker: HybridReRanker | None = None,
    ) -> None:
        self._retriever = retriever
        self._session = session
        self._query_engine = query_engine or QueryUnderstandingEngine()
        self._reranker = reranker or HybridReRanker()

    async def build_context(self, request: HybridContextRequest) -> HybridContextBundle:
        """
        Executes the 7-Stage retrieval pipeline:
        1. Query Understanding (Intent & AST Filter Extraction)
        2. Dense Vector Search (Qdrant Semantic Hits)
        3. Payload & Metadata Filtering
        4. Relational Graph Expansion (Callers / Callees / Centrality)
        5. Hybrid Re-Ranking (Score Fusion + Graph Centrality Boost)
        6. Context Token Budgeting & Deduplication
        7. Prompt Assembly & Markdown Formatting
        """
        # Stage 1: Query Understanding
        parsed_query = self._query_engine.analyze_query(request.query_text)

        effective_levels = request.levels or parsed_query.suggested_levels

        # Stage 2 & 3: Dense Vector Search & Metadata Filtering
        search_req = SemanticSearchRequest(
            query_text=request.query_text,
            repository_id=request.repository_id,
            limit=request.vector_limit,
            levels=effective_levels,
            score_threshold=request.score_threshold,
        )
        raw_vector_hits = await self._retriever.search(search_req)

        # Stage 4: Relational Graph Expansion
        file_paths: set[str] = {hit.file_path for hit in raw_vector_hits if hit.file_path}
        graph_lines: list[str] = []
        graph_context_symbols: list[SymbolResult] = []

        if self._session is not None and request.include_graph_impact:
            symbol_service = SymbolQueryService(self._session)
            context_builder = RepositoryContextBuilder(self._session)

            symbol_ids: set[UUID] = set()
            for hit in raw_vector_hits:
                sym_id_str = hit.metadata.get("symbol_id")
                if sym_id_str:
                    try:
                        symbol_ids.add(UUID(str(sym_id_str)))
                    except ValueError:
                        pass
                elif hit.symbol_name:
                    found = await symbol_service.search_symbols(
                        request.repository_id,
                        SymbolQueryFilter(
                            repo_id=request.repository_id,
                            name=hit.symbol_name,
                        ),
                    )
                    for f in found:
                        symbol_ids.add(f.id)

            if symbol_ids:
                graph_lines.append("## AST Graph & Impact Context")
                for sid in list(symbol_ids)[:5]:
                    related = await context_builder.get_related_symbols(sid)
                    if related:
                        graph_context_symbols.extend(related)
                        graph_lines.append(f"### Symbol ID: {sid}")
                        for r in related[:5]:
                            rel_name = r.qualified_name or r.name
                            graph_lines.append(
                                f"- Related ({r.kind.value}): {rel_name} (File: {r.file_path})"
                            )
                            if r.file_path:
                                file_paths.add(r.file_path)

        # Stage 5: Hybrid Re-Ranking
        ranked_vector_hits = self._reranker.rerank(
            parsed_query=parsed_query,
            hits=raw_vector_hits,
            graph_context_symbols=graph_context_symbols,
        )

        graph_context_prompt = "\n".join(graph_lines)

        # Stage 6 & 7: Context Budgeting & Markdown Formatting
        context_parts: list[str] = [
            f"# Retrieved Code Context for Query: '{request.query_text}'",
            f"**Intent**: `{parsed_query.intent.value}`",
            "",
            "## Semantic Vector Results",
        ]

        if not ranked_vector_hits:
            context_parts.append("(No semantically relevant code chunks found)")
        else:
            for idx, hit in enumerate(ranked_vector_hits, start=1):
                sym_label = f" [{hit.qualified_name or hit.symbol_name}]" if hit.symbol_name else ""
                header = (
                    f"### Match {idx}: File `{hit.file_path}`{sym_label} "
                    f"(Level {hit.level}, Score: {hit.score:.3f})"
                )
                context_parts.extend(
                    [
                        header,
                        "```",
                        hit.content,
                        "```",
                        "",
                    ]
                )

        if graph_context_prompt:
            context_parts.extend(["", graph_context_prompt])

        combined_context = "\n".join(context_parts)
        token_count_estimate = len(combined_context) // 4

        logger.info(
            "HybridContextBuilder generated 7-stage bundle with %d vector hits, "
            "%d graph contexts (~%d tokens)",
            len(ranked_vector_hits),
            len(graph_lines),
            token_count_estimate,
        )

        return HybridContextBundle(
            query_text=request.query_text,
            repository_id=request.repository_id,
            vector_hits=ranked_vector_hits,
            graph_context_prompt=graph_context_prompt,
            combined_context=combined_context,
            token_count_estimate=token_count_estimate,
            referenced_file_paths=sorted(list(file_paths)),
        )
