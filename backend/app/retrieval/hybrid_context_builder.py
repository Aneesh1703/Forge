"""
Graph + Vector Hybrid Context Builder

Fuses semantic vector similarity search results with AST graph structural relationships
(callers, callees, inheritance, module imports) to generate rich AI prompt context.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.query.context_builder import RepositoryContextBuilder
from app.query.models import SymbolQueryFilter
from app.query.symbol_query_service import SymbolQueryService
from app.retrieval.models import (
    HybridContextBundle,
    HybridContextRequest,
    SemanticSearchRequest,
)
from app.retrieval.semantic_retriever import SemanticRetriever

logger = logging.getLogger(__name__)


class HybridContextBuilder:
    """
    Builder engine for fusing semantic retrieval with graph structural intelligence.
    """

    def __init__(
        self,
        retriever: SemanticRetriever,
        session: AsyncSession | None = None,
    ) -> None:
        self._retriever = retriever
        self._session = session

    async def build_context(self, request: HybridContextRequest) -> HybridContextBundle:
        """
        1. Retrieve top-k semantic vector hits via SemanticRetriever.
        2. Extract related graph symbols & impact context for matched symbols (if session present).
        3. Fuse semantic chunks and structural graph context into a cohesive prompt bundle.
        """
        # 1. Execute vector search
        search_req = SemanticSearchRequest(
            query_text=request.query_text,
            repository_id=request.repository_id,
            limit=request.vector_limit,
            levels=request.levels,
            score_threshold=request.score_threshold,
        )
        vector_hits = await self._retriever.search(search_req)

        # 2. Extract referenced files & symbol IDs
        file_paths: set[str] = {hit.file_path for hit in vector_hits if hit.file_path}
        graph_lines: list[str] = []

        # 3. Augment with AST Graph Context if session is available
        if self._session is not None and request.include_graph_impact:
            symbol_service = SymbolQueryService(self._session)
            context_builder = RepositoryContextBuilder(self._session)

            symbol_ids: set[UUID] = set()
            for hit in vector_hits:
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
                for sid in list(symbol_ids)[:5]:  # Limit top 5 symbols for graph context
                    related = await context_builder.get_related_symbols(sid)
                    if related:
                        graph_lines.append(f"### Symbol ID: {sid}")
                        for r in related[:5]:
                            rel_name = r.qualified_name or r.name
                            graph_lines.append(
                                f"- Related ({r.kind.value}): {rel_name} (File: {r.file_path})"
                            )
                            if r.file_path:
                                file_paths.add(r.file_path)

        graph_context_prompt = "\n".join(graph_lines)

        # 4. Construct final combined context prompt
        context_parts: list[str] = [
            f"# Retrieved Code Context for Query: '{request.query_text}'",
            "",
            "## Semantic Vector Results",
        ]

        if not vector_hits:
            context_parts.append("(No semantically relevant code chunks found)")
        else:
            for idx, hit in enumerate(vector_hits, start=1):
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
            "HybridContextBuilder generated bundle with %d vector hits, "
            "%d graph contexts (~%d tokens)",
            len(vector_hits),
            len(graph_lines),
            token_count_estimate,
        )

        return HybridContextBundle(
            query_text=request.query_text,
            repository_id=request.repository_id,
            vector_hits=vector_hits,
            graph_context_prompt=graph_context_prompt,
            combined_context=combined_context,
            token_count_estimate=token_count_estimate,
            referenced_file_paths=sorted(list(file_paths)),
        )
