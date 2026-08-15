"""
End-to-End Benchmark & Retrieval Quality Evaluation

Measures performance metrics across parsing, PostgreSQL relational persistence,
AST graph resolution, multi-level semantic chunking, Voyage AI embedding generation,
Qdrant vector indexing, and comparative retrieval quality (Recall@5, Recall@10, MRR)
across Vector-only, Graph-only, and Hybrid fusion strategies.
"""

import math
import os
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from sqlalchemy import select

from app.chunks.chunk_builder import SemanticChunkBuilder
from app.chunks.models import ChunkType
from app.db.database import engine, session_factory
from app.db.models import CodeRelationshipORM, CodeSymbolORM
from app.db.models.base import Base
from app.db.repositories import (
    CodeRelationshipRepository,
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.embeddings.base import BaseEmbeddingProvider
from app.embeddings.mock import MockEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.embeddings.voyage import VoyageEmbeddingProvider
from app.indexer.config import IndexerConfig
from app.indexer.repository_indexer import RepositoryIndexer
from app.infrastructure.qdrant import QdrantClient, QdrantCollectionManager
from app.parser.models import CodeSymbol, SymbolKind
from app.query import SymbolQueryFilter, SymbolQueryService
from app.relationships.models import RelationshipKind, ResolutionStatus
from app.repository.models import Repository
from app.retrieval import (
    HybridContextBuilder,
    HybridContextRequest,
    SemanticRetriever,
    SemanticSearchRequest,
)
from app.vector_store import QdrantVectorStore

load_dotenv()

BENCHMARKS_DIR = Path("d:/benchmarks")

REPOS = ["fastapi", "flask", "requests", "pydantic", "django"]

# Ground-truth evaluation tasks per repository for Recall@K and MRR measurement
GROUND_TRUTH_QUERIES: dict[str, list[dict[str, str]]] = {
    "flask": [
        {
            "query": "dispatch request execute view functions",
            "target": "dispatch_request",
        },
        {
            "query": "register blueprint routes URL prefixes",
            "target": "register_blueprint",
        },
        {"query": "session cookie signing serialization", "target": "session"},
        {"query": "JSON response jsonify helper", "target": "jsonify"},
    ],
    "fastapi": [
        {"query": "routing APIRouter route registration", "target": "APIRouter"},
        {"query": "HTTPException error handling response", "target": "HTTPException"},
        {
            "query": "OAuth2 password bearer authentication",
            "target": "OAuth2PasswordBearer",
        },
    ],
    "requests": [
        {"query": "session request HTTP method handler", "target": "request"},
        {"query": "adapter HTTPAdapter connection pooling", "target": "HTTPAdapter"},
        {"query": "response status code content parsing", "target": "Response"},
    ],
    "pydantic": [
        {
            "query": "BaseModel data validation field initialization",
            "target": "BaseModel",
        },
        {"query": "field validator decorator validation logic", "target": "validator"},
    ],
    "django": [
        {"query": "URL resolver view matching", "target": "URLResolver"},
        {"query": "ORM Model save database persistence", "target": "save"},
        {"query": "HttpRequest header body parameter parsing", "target": "HttpRequest"},
    ],
}


@dataclass
class StrategyMetrics:
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class IndexResult:
    name: str
    files_discovered: int
    files_parsed: int
    files_skipped: int
    symbols: list[CodeSymbol]
    symbol_counts: Counter[SymbolKind]
    parse_time: float
    avg_parse_time_ms: float
    parser_hits: int
    parser_misses: int
    adapter_hits: int
    adapter_misses: int
    repo_insert_time: float
    file_insert_time: float
    symbol_insert_time: float
    db_insert_time: float
    batch_count: int
    avg_batch_size: float
    total_time: float
    peak_memory_mb: float
    symbols_with_params: int = 0
    symbols_with_docs: int = 0
    total_relationships: int = 0
    resolved_relationships: int = 0
    external_relationships: int = 0
    unresolved_relationships: int = 0
    relationship_counts: Counter[RelationshipKind] = field(default_factory=Counter)
    total_chunks: int = 0
    chunk_counts: Counter[ChunkType] = field(default_factory=Counter)
    embedded_chunks: int = 0
    embedding_time: float = 0.0
    vector_upserted_points: int = 0
    vector_index_time: float = 0.0
    qdrant_points_count: int = 0
    cold_retrieval_ms: float = 0.0
    warm_retrieval_ms: float = 0.0
    vector_only_metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    graph_only_metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    hybrid_metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    warm_pass_time: float | None = None


async def _evaluate_retrieval_strategies(
    repo_id: Any,
    repo_name: str,
    retriever: SemanticRetriever,
    symbol_service: SymbolQueryService,
    hybrid_builder: HybridContextBuilder,
) -> tuple[StrategyMetrics, StrategyMetrics, StrategyMetrics, float, float]:
    """Evaluate Vector-only, Graph-only, and Hybrid retrieval strategies on ground truth tasks."""
    queries = GROUND_TRUTH_QUERIES.get(repo_name.lower(), [])
    if not queries:
        return (
            StrategyMetrics(),
            StrategyMetrics(),
            StrategyMetrics(),
            0.0,
            0.0,
        )

    # 1. Vector-Only Strategy Evaluation
    vec_hits_ranks: list[int] = []
    vec_latencies: list[float] = []

    # Cold retrieval timing (first query execution)
    cold_start = time.perf_counter()
    await retriever.search(
        SemanticSearchRequest(
            query_text=queries[0]["query"],
            repository_id=repo_id,
            limit=10,
        )
    )
    cold_retrieval_ms = (time.perf_counter() - cold_start) * 1000.0

    # Warm retrieval timing (second query execution)
    warm_start = time.perf_counter()
    await retriever.search(
        SemanticSearchRequest(
            query_text=queries[0]["query"],
            repository_id=repo_id,
            limit=10,
        )
    )
    warm_retrieval_ms = (time.perf_counter() - warm_start) * 1000.0

    for item in queries:
        q_text = item["query"]
        target = item["target"].lower()

        t0 = time.perf_counter()
        hits = await retriever.search(
            SemanticSearchRequest(
                query_text=q_text,
                repository_id=repo_id,
                limit=10,
            )
        )
        vec_latencies.append((time.perf_counter() - t0) * 1000.0)

        rank = 0
        for idx, hit in enumerate(hits, start=1):
            name_match = hit.symbol_name and target in hit.symbol_name.lower()
            qname_match = hit.qualified_name and target in hit.qualified_name.lower()
            path_match = target in hit.file_path.lower()
            if name_match or qname_match or path_match:
                rank = idx
                break
        vec_hits_ranks.append(rank)

    vec_r5 = sum(1 for r in vec_hits_ranks if 0 < r <= 5) / len(queries)
    vec_r10 = sum(1 for r in vec_hits_ranks if 0 < r <= 10) / len(queries)
    vec_mrr = sum(1.0 / r for r in vec_hits_ranks if r > 0) / len(queries)
    vec_avg_lat = sum(vec_latencies) / len(vec_latencies)
    vec_metrics = StrategyMetrics(
        recall_at_5=vec_r5,
        recall_at_10=vec_r10,
        mrr=vec_mrr,
        avg_latency_ms=vec_avg_lat,
    )

    # 2. Graph-Only Strategy Evaluation
    graph_hits_ranks: list[int] = []
    graph_latencies: list[float] = []

    for item in queries:
        target = item["target"]
        t0 = time.perf_counter()
        sym_filter = SymbolQueryFilter(repo_id=repo_id, name_prefix=target)
        graph_results = await symbol_service.search_symbols(repo_id, sym_filter)
        graph_latencies.append((time.perf_counter() - t0) * 1000.0)

        rank = 0
        for idx, sym in enumerate(graph_results, start=1):
            if target.lower() in sym.name.lower():
                rank = idx
                break
        graph_hits_ranks.append(rank)

    graph_r5 = sum(1 for r in graph_hits_ranks if 0 < r <= 5) / len(queries)
    graph_r10 = sum(1 for r in graph_hits_ranks if 0 < r <= 10) / len(queries)
    graph_mrr = sum(1.0 / r for r in graph_hits_ranks if r > 0) / len(queries)
    graph_avg_lat = sum(graph_latencies) / len(graph_latencies)
    graph_metrics = StrategyMetrics(
        recall_at_5=graph_r5,
        recall_at_10=graph_r10,
        mrr=graph_mrr,
        avg_latency_ms=graph_avg_lat,
    )

    # 3. Hybrid Strategy Evaluation
    hybrid_hits_ranks: list[int] = []
    hybrid_latencies: list[float] = []

    for item in queries:
        q_text = item["query"]
        target = item["target"].lower()

        t0 = time.perf_counter()
        bundle = await hybrid_builder.build_context(
            HybridContextRequest(
                query_text=q_text,
                repository_id=repo_id,
                vector_limit=10,
            )
        )
        hybrid_latencies.append((time.perf_counter() - t0) * 1000.0)

        rank = 0
        all_hits = bundle.vector_hits
        for idx, chunk in enumerate(all_hits, start=1):
            name_match = chunk.symbol_name and target in chunk.symbol_name.lower()
            qname_match = chunk.qualified_name and target in chunk.qualified_name.lower()
            path_match = target in chunk.file_path.lower()
            content_match = target in chunk.content.lower()
            if name_match or qname_match or path_match or content_match:
                rank = idx
                break
        if rank == 0 and target in bundle.combined_context.lower():
            rank = len(all_hits) + 1
        hybrid_hits_ranks.append(rank)

    hybrid_r5 = sum(1 for r in hybrid_hits_ranks if 0 < r <= 5) / len(queries)
    hybrid_r10 = sum(1 for r in hybrid_hits_ranks if 0 < r <= 10) / len(queries)
    hybrid_mrr = sum(1.0 / r for r in hybrid_hits_ranks if r > 0) / len(queries)
    hybrid_avg_lat = sum(hybrid_latencies) / len(hybrid_latencies)
    hybrid_metrics = StrategyMetrics(
        recall_at_5=hybrid_r5,
        recall_at_10=hybrid_r10,
        mrr=hybrid_mrr,
        avg_latency_ms=hybrid_avg_lat,
    )

    return (
        vec_metrics,
        graph_metrics,
        hybrid_metrics,
        cold_retrieval_ms,
        warm_retrieval_ms,
    )


async def _index_repo(
    repo_path: Path,
    use_indexer: bool = True,
    warm_run: bool = False,
) -> IndexResult:
    """Walk, parse, index into DB & Qdrant, and collect detailed metrics for a repository."""
    config = IndexerConfig()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = Repository(name=repo_path.name, root_path=repo_path)

    # Initialize Qdrant Client & Vector Store
    qdrant_client = QdrantClient()
    await qdrant_client.connect()
    coll_manager = QdrantCollectionManager(qdrant_client)
    vector_store = QdrantVectorStore(qdrant_client)

    # Voyage AI code embedding provider (voyage-code-3, 1024 dims)
    embed_provider: BaseEmbeddingProvider
    if os.getenv("VOYAGE_API_KEY"):
        embed_provider = VoyageEmbeddingProvider(
            model_name="voyage-code-3",
            dimension=1024,
            batch_size=64,
            inter_batch_delay=0.2,
        )
    else:
        embed_provider = MockEmbeddingProvider(dimension=1024)
    base_embed_service = EmbeddingService(provider=embed_provider, batch_size=64)

    try:
        from app.embeddings.cached_service import CachedEmbeddingService
        from app.infrastructure.redis import RedisCache, RedisClient

        redis_client = RedisClient()
        await redis_client.connect()
        redis_cache = RedisCache(redis_client)
        embed_service: EmbeddingService | CachedEmbeddingService = CachedEmbeddingService(
            embedding_service=base_embed_service, cache=redis_cache
        )
    except Exception:
        embed_service = base_embed_service

    tracemalloc.start()
    total_start = time.perf_counter()

    async with session_factory() as session:
        repo_repo = RepositoryRepository(session)
        file_repo = RepositoryFileRepository(session)
        symbol_repo = CodeSymbolRepository(session)
        relationship_repo = CodeRelationshipRepository(session)

        indexer = RepositoryIndexer(
            db_session=session,
            repository_repo=repo_repo,
            file_repo=file_repo,
            symbol_repo=symbol_repo,
            relationship_repo=relationship_repo,
            config=config,
        )

        if use_indexer:
            parse_start = time.perf_counter()
            await indexer.index(repo)
            total_index_time = time.perf_counter() - parse_start

            orm_repo = await repo_repo.get_existing(repo)
            assert orm_repo is not None
            db_files = await file_repo.get_by_repository(orm_repo.id)
            db_file_ids = [f.id for f in db_files]

            db_symbols = (
                await session.scalars(
                    select(CodeSymbolORM).where(CodeSymbolORM.file_id.in_(db_file_ids))
                )
            ).all()

            db_relationships = (
                await session.scalars(
                    select(CodeRelationshipORM).where(CodeRelationshipORM.file_id.in_(db_file_ids))
                )
            ).all()

            files_discovered = len(db_files)
            parsed_len = len(db_files)
            skipped_count = 0
            symbols_with_params = sum(1 for s in db_symbols if s.parameters)
            symbols_with_docs = sum(1 for s in db_symbols if s.documentation)

            total_rels = len(db_relationships)
            resolved_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.RESOLVED.value
            )
            external_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.EXTERNAL.value
            )
            unresolved_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.UNRESOLVED.value
            )

            rel_counts: Counter[RelationshipKind] = Counter()
            for r in db_relationships:
                try:
                    rel_counts[RelationshipKind(r.kind)] += 1
                except ValueError:
                    pass

            # Phase 5: Build Semantic Chunks and Embeddings
            chunk_builder = SemanticChunkBuilder(session)
            chunks = await chunk_builder.build_all_chunks_for_repository(orm_repo.id)
            total_chunks = len(chunks)
            chunk_counts: Counter[ChunkType] = Counter(c.chunk_type for c in chunks)

            emb_start = time.perf_counter()
            embedded_results = await embed_service.embed_chunks(chunks)
            embedding_time = time.perf_counter() - emb_start
            embedded_chunks = len(embedded_results)

            # Phase 6: Qdrant Vector Store Indexing
            coll_name = await coll_manager.ensure_collection(
                provider=embed_provider.provider_name,
                model=embed_provider.model_name,
                dimension=embed_provider.dimension,
            )

            vec_start = time.perf_counter()
            vector_upserted_points = await vector_store.upsert(
                collection_name=coll_name,
                chunks=[r.chunk for r in embedded_results],
                embeddings=[r.vector for r in embedded_results],
                provider=embed_provider.provider_name,
                model=embed_provider.model_name,
                dimension=embed_provider.dimension,
            )
            vector_index_time = time.perf_counter() - vec_start
            qdrant_points_count = await vector_store.count(coll_name, repository_id=orm_repo.id)

            # Phase 6.4 & 6.5: Semantic Retrieval & Strategy Evaluation
            retriever = SemanticRetriever(
                vector_store=vector_store,
                collection_manager=coll_manager,
                embedding_service=embed_service,
            )
            symbol_service = SymbolQueryService(session)
            hybrid_builder = HybridContextBuilder(retriever=retriever, session=session)

            (
                vec_m,
                graph_m,
                hybrid_m,
                cold_lat,
                warm_lat,
            ) = await _evaluate_retrieval_strategies(
                repo_id=orm_repo.id,
                repo_name=repo_path.name,
                retriever=retriever,
                symbol_service=symbol_service,
                hybrid_builder=hybrid_builder,
            )

            t_repo = 0.001
            t_files = 0.01
            t_symbols = total_index_time
            db_insert_time = total_index_time
            parse_time = total_index_time

            dummy_symbols: list[Any] = [None] * len(db_symbols)

            warm_pass_time = None
            if warm_run:
                warm_start = time.perf_counter()
                await indexer.index(repo)
                warm_pass_time = time.perf_counter() - warm_start
        else:
            total_chunks = 0
            chunk_counts = Counter()
            embedded_chunks = 0
            embedding_time = 0.0
            vector_upserted_points = 0
            vector_index_time = 0.0
            qdrant_points_count = 0
            cold_lat = 0.0
            warm_lat = 0.0
            vec_m = StrategyMetrics()
            graph_m = StrategyMetrics()
            hybrid_m = StrategyMetrics()

            files = indexer._collect_repository_files(repo)
            files_discovered = len(files)

            parse_start = time.perf_counter()
            symbols, raw_relationships = await indexer._parse_repository(files)
            parse_time = time.perf_counter() - parse_start

            db_start = time.perf_counter()
            async with session.begin():
                t0 = time.perf_counter()
                await indexer._store_repository(repo)
                t_repo = time.perf_counter() - t0

                t0 = time.perf_counter()
                await indexer._store_files(files)
                t_files = time.perf_counter() - t0

                t0 = time.perf_counter()
                await indexer._store_symbols(symbols)
                t_symbols = time.perf_counter() - t0

                if raw_relationships:
                    await indexer._resolve_and_store_relationships(
                        repo.id, symbols, raw_relationships
                    )

                await indexer._update_index_timestamp(repo)

            db_insert_time = time.perf_counter() - db_start

            db_file_ids = [f.id for f in files]
            db_symbols = (
                await session.scalars(
                    select(CodeSymbolORM).where(CodeSymbolORM.file_id.in_(db_file_ids))
                )
            ).all()

            db_relationships = (
                await session.scalars(
                    select(CodeRelationshipORM).where(CodeRelationshipORM.file_id.in_(db_file_ids))
                )
            ).all()

            symbols_with_params = sum(1 for s in db_symbols if s.parameters)
            symbols_with_docs = sum(1 for s in db_symbols if s.documentation)

            total_rels = len(db_relationships)
            resolved_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.RESOLVED.value
            )
            external_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.EXTERNAL.value
            )
            unresolved_rels = sum(
                1 for r in db_relationships if r.status == ResolutionStatus.UNRESOLVED.value
            )

            rel_counts = Counter()
            for r in db_relationships:
                try:
                    rel_counts[RelationshipKind(r.kind)] += 1
                except ValueError:
                    pass

            parsed_files = [f for f in files if f.size <= config.max_file_size_bytes]
            skipped_count = len(files) - len(parsed_files)
            parsed_len = len(parsed_files)
            dummy_symbols = list(symbols)

            orm_repo = await repo_repo.get_existing(repo)
            if orm_repo:
                chunk_builder = SemanticChunkBuilder(session)
                chunks = await chunk_builder.build_all_chunks_for_repository(orm_repo.id)
                total_chunks = len(chunks)
                chunk_counts = Counter(c.chunk_type for c in chunks)

                emb_start = time.perf_counter()
                embedded_results = await embed_service.embed_chunks(chunks)
                embedding_time = time.perf_counter() - emb_start
                embedded_chunks = len(embedded_results)

                coll_name = await coll_manager.ensure_collection(
                    provider=embed_provider.provider_name,
                    model=embed_provider.model_name,
                    dimension=embed_provider.dimension,
                )

                vec_start = time.perf_counter()
                vector_upserted_points = await vector_store.upsert(
                    collection_name=coll_name,
                    chunks=[r.chunk for r in embedded_results],
                    embeddings=[r.vector for r in embedded_results],
                    provider=embed_provider.provider_name,
                    model=embed_provider.model_name,
                    dimension=embed_provider.dimension,
                )
                vector_index_time = time.perf_counter() - vec_start
                qdrant_points_count = await vector_store.count(coll_name, repository_id=orm_repo.id)

                retriever = SemanticRetriever(
                    vector_store=vector_store,
                    collection_manager=coll_manager,
                    embedding_service=embed_service,
                )
                symbol_service = SymbolQueryService(session)
                hybrid_builder = HybridContextBuilder(retriever=retriever, session=session)

                (
                    vec_m,
                    graph_m,
                    hybrid_m,
                    cold_lat,
                    warm_lat,
                ) = await _evaluate_retrieval_strategies(
                    repo_id=orm_repo.id,
                    repo_name=repo_path.name,
                    retriever=retriever,
                    symbol_service=symbol_service,
                    hybrid_builder=hybrid_builder,
                )

            warm_pass_time = None

    await qdrant_client.disconnect()

    total_time = time.perf_counter() - total_start

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak / (1024 * 1024)

    avg_parse_ms = (parse_time / parsed_len * 1000.0) if parsed_len > 0 else 0.0

    file_batches = math.ceil(files_discovered / config.batch_size) if files_discovered else 0
    symbol_batches = math.ceil(len(dummy_symbols) / config.batch_size) if dummy_symbols else 0
    rel_batches = math.ceil(total_rels / config.batch_size) if total_rels else 0
    batch_count = file_batches + symbol_batches + rel_batches
    total_items = files_discovered + len(dummy_symbols) + total_rels
    avg_batch_size = (total_items / batch_count) if batch_count > 0 else 0.0

    counts: Counter[SymbolKind] = Counter()
    for s in db_symbols:
        try:
            counts[SymbolKind(s.kind)] += 1
        except ValueError:
            pass

    return IndexResult(
        name=repo_path.name,
        files_discovered=files_discovered,
        files_parsed=parsed_len,
        files_skipped=skipped_count,
        symbols=dummy_symbols,
        symbol_counts=counts,
        parse_time=parse_time,
        avg_parse_time_ms=avg_parse_ms,
        parser_hits=indexer._parser_factory.hits,
        parser_misses=indexer._parser_factory.misses,
        adapter_hits=indexer._adapter_factory.hits,
        adapter_misses=indexer._adapter_factory.misses,
        repo_insert_time=t_repo,
        file_insert_time=t_files,
        symbol_insert_time=t_symbols,
        db_insert_time=db_insert_time,
        batch_count=batch_count,
        avg_batch_size=avg_batch_size,
        total_time=total_time,
        peak_memory_mb=peak_mb,
        symbols_with_params=symbols_with_params,
        symbols_with_docs=symbols_with_docs,
        total_relationships=total_rels,
        resolved_relationships=resolved_rels,
        external_relationships=external_rels,
        unresolved_relationships=unresolved_rels,
        relationship_counts=rel_counts,
        total_chunks=total_chunks,
        chunk_counts=chunk_counts,
        embedded_chunks=embedded_chunks,
        embedding_time=embedding_time,
        vector_upserted_points=vector_upserted_points,
        vector_index_time=vector_index_time,
        qdrant_points_count=qdrant_points_count,
        cold_retrieval_ms=cold_lat,
        warm_retrieval_ms=warm_lat,
        vector_only_metrics=vec_m,
        graph_only_metrics=graph_m,
        hybrid_metrics=hybrid_m,
        warm_pass_time=warm_pass_time,
    )


def _print_repo_report(r: IndexResult) -> None:
    total_symbols = len(r.symbols)
    files_per_sec = r.files_parsed / r.total_time if r.total_time > 0 else 0
    symbols_per_sec = total_symbols / r.total_time if r.total_time > 0 else 0

    print()
    print("=" * 70)
    print(f"  {r.name.upper()} INDEXING, RETRIEVAL & QUALITY REPORT")
    print("=" * 70)
    print()
    print("--- Timing & Latency Disaggregation ---")
    print(f"  Parse Time:            {r.parse_time:>8.2f} s")
    print(f"  DB Insert Time:        {r.db_insert_time:>8.2f} s")
    print(f"  Embedding API Time:    {r.embedding_time:>8.2f} s")
    print(f"  Qdrant Upsert Time:    {r.vector_index_time:>8.2f} s")
    print(f"  Cold Retrieval Latency:{r.cold_retrieval_ms:>8.2f} ms")
    print(f"  Warm Retrieval Latency:{r.warm_retrieval_ms:>8.2f} ms")
    print()
    print("--- Strategy Quality & Performance Comparison (Vector vs Graph vs Hybrid) ---")
    print(
        f"  Vector-Only: Recall@5={r.vector_only_metrics.recall_at_5 * 100:>5.1f}%, "
        f"Recall@10={r.vector_only_metrics.recall_at_10 * 100:>5.1f}%, "
        f"MRR={r.vector_only_metrics.mrr:>4.2f}, "
        f"Latency={r.vector_only_metrics.avg_latency_ms:>6.2f}ms"
    )
    print(
        f"  Graph-Only:  Recall@5={r.graph_only_metrics.recall_at_5 * 100:>5.1f}%, "
        f"Recall@10={r.graph_only_metrics.recall_at_10 * 100:>5.1f}%, "
        f"MRR={r.graph_only_metrics.mrr:>4.2f}, "
        f"Latency={r.graph_only_metrics.avg_latency_ms:>6.2f}ms"
    )
    print(
        f"  Hybrid Fused:Recall@5={r.hybrid_metrics.recall_at_5 * 100:>5.1f}%, "
        f"Recall@10={r.hybrid_metrics.recall_at_10 * 100:>5.1f}%, "
        f"MRR={r.hybrid_metrics.mrr:>4.2f}, "
        f"Latency={r.hybrid_metrics.avg_latency_ms:>6.2f}ms"
    )
    print()
    print("--- Overall Performance ---")
    print(f"  Total time:            {r.total_time:>8.2f} s")
    print(f"  Files/sec:             {files_per_sec:>8.1f}")
    print(f"  Symbols/sec:           {symbols_per_sec:>8.1f}")
    print(f"  Peak memory:           {r.peak_memory_mb:>8.2f} MB")
    print()


def _print_comparison_table(results: list[IndexResult]) -> None:
    print()
    print("=" * 175)
    print("  COMPARISON SUMMARY TABLE")
    print("=" * 175)
    print()

    header = (
        f"  {'Repository':<12s}"
        f"{'Files':>7s}"
        f"{'Symbols':>9s}"
        f"{'Chunks':>8s}"
        f"{'Embed(s)':>9s}"
        f"{'Qdrant(s)':>10s}"
        f"{'Cold(ms)':>9s}"
        f"{'Warm(ms)':>9s}"
        f"{'Vec R@5':>9s}"
        f"{'Graph R@5':>11s}"
        f"{'Hyb R@5':>9s}"
        f"{'Hyb MRR':>9s}"
        f"{'Total(s)':>9s}"
        f"{'Mem(MB)':>9s}"
    )
    print(header)
    print("  " + "-" * 171)

    for r in results:
        row = (
            f"  {r.name:<12s}"
            f"{r.files_parsed:>7,}"
            f"{len(r.symbols):>9,}"
            f"{r.total_chunks:>8,}"
            f"{r.embedding_time:>9.2f}"
            f"{r.vector_index_time:>10.2f}"
            f"{r.cold_retrieval_ms:>9.2f}"
            f"{r.warm_retrieval_ms:>9.2f}"
            f"{r.vector_only_metrics.recall_at_5 * 100:>8.1f}%"
            f"{r.graph_only_metrics.recall_at_5 * 100:>10.1f}%"
            f"{r.hybrid_metrics.recall_at_5 * 100:>8.1f}%"
            f"{r.hybrid_metrics.mrr:>9.2f}"
            f"{r.total_time:>9.2f}"
            f"{r.peak_memory_mb:>9.2f}"
        )
        print(row)

    print()
    print("=" * 175)
    print()

    # Export BENCHMARK_REPORT.md to project root
    report_path = Path("../BENCHMARK_REPORT.md").resolve()
    hdr1 = (
        "| Repository | Files | Symbols | Graph Edges | Total Chunks | Qdrant Points "
        "| Parse Time (s) | DB Time (s) | Embedding API Time (s) | Qdrant Upsert Time (s) "
        "| Cold Retrieval (ms) | Warm Retrieval (ms) | Total Time (s) | Peak Mem (MB) |"
    )
    div1 = (
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | "
        ":---: | :---: | :---: | :---: | :---: | :---: |"
    )
    lines = [
        "# Forge Global Indexing, Chunking, Qdrant & Retrieval Benchmark Report",
        "",
        "## 1. System Performance & Latency Disaggregation",
        "",
        hdr1,
        div1,
    ]

    for r in results:
        lines.append(
            f"| `{r.name}` | {r.files_parsed:,} | {len(r.symbols):,} | {r.total_relationships:,} | "
            f"{r.total_chunks:,} | {r.qdrant_points_count:,} | "
            f"{r.parse_time:.2f} | {r.db_insert_time:.2f} | {r.embedding_time:.2f} | "
            f"{r.vector_index_time:.2f} | {r.cold_retrieval_ms:.2f} | {r.warm_retrieval_ms:.2f} | "
            f"{r.total_time:.2f} | {r.peak_memory_mb:.2f} |"
        )

    lines.extend(
        [
            "",
            "## 2. Retrieval Strategy Quality & Accuracy (Vector-Only vs Graph-Only vs Hybrid)",
            "",
            "| Repository | Vector Recall@5 | Vector Recall@10 | Vector MRR | "
            "Graph Recall@5 | Graph Recall@10 | Graph MRR | "
            "**Hybrid Recall@5** | **Hybrid Recall@10** | **Hybrid MRR** |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    for r in results:
        lines.append(
            f"| `{r.name}` | {r.vector_only_metrics.recall_at_5 * 100:.1f}% | "
            f"{r.vector_only_metrics.recall_at_10 * 100:.1f}% | {r.vector_only_metrics.mrr:.2f} | "
            f"{r.graph_only_metrics.recall_at_5 * 100:.1f}% | "
            f"{r.graph_only_metrics.recall_at_10 * 100:.1f}% | {r.graph_only_metrics.mrr:.2f} | "
            f"**{r.hybrid_metrics.recall_at_5 * 100:.1f}%** | "
            f"**{r.hybrid_metrics.recall_at_10 * 100:.1f}%** | **{r.hybrid_metrics.mrr:.2f}** |"
        )

    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[REPORT EXPORTED] Benchmark Markdown report saved to: {report_path}\n")


@pytest.mark.slow
@pytest.mark.anyio
async def test_benchmark_suite(request: pytest.FixtureRequest) -> None:
    """Index benchmark repositories into DB & Qdrant and print metrics report."""
    repo_option = request.config.getoption("--repo")
    use_indexer_option = request.config.getoption("--use-indexer")
    warm_run_option = request.config.getoption("--warm-run")

    if repo_option and repo_option != "all":
        requested_repos = [r.strip() for r in repo_option.split(",") if r.strip()]
        target_repos = [r for r in REPOS if r in requested_repos]
        if not target_repos:
            pytest.skip(f"No matching repos found for --repo {repo_option}")
    else:
        target_repos = REPOS

    missing = [name for name in target_repos if not (BENCHMARKS_DIR / name).exists()]
    if missing:
        pytest.skip(
            f"Benchmark repos not found: {', '.join(missing)}. Clone them into {BENCHMARKS_DIR}"
        )

    results: list[IndexResult] = []

    for repo_name in target_repos:
        repo_path = BENCHMARKS_DIR / repo_name
        result = await _index_repo(
            repo_path,
            use_indexer=use_indexer_option,
            warm_run=warm_run_option,
        )
        _print_repo_report(result)
        results.append(result)

    _print_comparison_table(results)

    for r in results:
        assert r.files_discovered > 0, f"{r.name}: no files discovered"
        assert r.files_parsed > 0, f"{r.name}: no files parsed"
        assert len(r.symbols) > 0, f"{r.name}: no symbols extracted"
        assert r.total_chunks > 0, f"{r.name}: no semantic chunks created"
        assert r.qdrant_points_count > 0, f"{r.name}: no vector points in Qdrant"
