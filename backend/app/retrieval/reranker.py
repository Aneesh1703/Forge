"""
Stage 5: Hybrid Re-Ranker

Fuses vector similarity scores with AST graph centrality, exact identifier matching,
and structural chunk level relevance to produce optimally ranked context hits.
"""

from app.query.models import SymbolResult
from app.retrieval.models import RetrievalChunkHit
from app.retrieval.query_understanding import ParsedQuery


class HybridReRanker:
    """
    Re-ranker engine scoring vector hits by combining semantic distance with graph centrality.
    """

    def __init__(
        self,
        vector_weight: float = 0.50,
        graph_weight: float = 0.30,
        exact_match_boost: float = 0.20,
    ) -> None:
        self._vector_weight = vector_weight
        self._graph_weight = graph_weight
        self._exact_match_boost = exact_match_boost

    def rerank(
        self,
        parsed_query: ParsedQuery,
        hits: list[RetrievalChunkHit],
        graph_context_symbols: list[SymbolResult] | None = None,
    ) -> list[RetrievalChunkHit]:
        """
        Re-ranks RetrievalChunkHits using vector similarity, exact identifier boosts,
        and graph relationship centrality.
        """
        if not hits:
            return []

        graph_sym_names: set[str] = set()
        if graph_context_symbols:
            for gs in graph_context_symbols:
                graph_sym_names.add(gs.name.lower())
                if gs.qualified_name:
                    graph_sym_names.add(gs.qualified_name.lower())

        target_ids = [tid.lower() for tid in parsed_query.target_identifiers]
        query_text_lower = parsed_query.raw_query.lower()

        scored_hits: list[tuple[float, RetrievalChunkHit]] = []

        for hit in hits:
            base_score = hit.score * self._vector_weight

            # Exact name / identifier match boost
            exact_boost = 0.0
            hit_sym = (hit.symbol_name or "").lower()
            hit_qname = (hit.qualified_name or "").lower()

            for tid in target_ids:
                if hit_sym == tid:
                    exact_boost += self._exact_match_boost
                elif tid in hit_sym or tid in hit_qname:
                    exact_boost += self._exact_match_boost * 0.5

            if not exact_boost:
                # Check for query words in symbol name
                for word in query_text_lower.split():
                    if len(word) > 2 and word in hit_sym:
                        exact_boost += 0.05

            # Graph centrality boost
            graph_boost = 0.0
            if hit_sym and hit_sym in graph_sym_names:
                graph_boost = self._graph_weight
            elif hit_qname and hit_qname in graph_sym_names:
                graph_boost = self._graph_weight

            # Level preference adjustment based on query intent
            level_boost = 0.0
            if hit.level in parsed_query.suggested_levels:
                level_boost = 0.05

            final_score = base_score + exact_boost + graph_boost + level_boost

            # Re-wrap hit with updated final score
            new_hit = RetrievalChunkHit(
                chunk_id=hit.chunk_id,
                score=round(final_score, 4),
                level=hit.level,
                chunk_type=hit.chunk_type,
                file_path=hit.file_path,
                symbol_name=hit.symbol_name,
                qualified_name=hit.qualified_name,
                content=hit.content,
                metadata=hit.metadata,
            )
            scored_hits.append((final_score, new_hit))

        # Sort descending by final score
        scored_hits.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored_hits]
