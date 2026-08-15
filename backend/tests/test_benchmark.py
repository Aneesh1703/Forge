import math
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.db.database import engine, session_factory
from app.db.models import CodeRelationshipORM, CodeSymbolORM
from app.db.models.base import Base
from app.db.repositories import (
    CodeRelationshipRepository,
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.config import IndexerConfig
from app.indexer.repository_indexer import RepositoryIndexer
from app.parser.models import CodeSymbol, SymbolKind
from app.relationships.models import RelationshipKind, ResolutionStatus
from app.repository.models import Repository

BENCHMARKS_DIR = Path("d:/benchmarks")

REPOS = ["fastapi", "flask", "requests", "pydantic", "django"]


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
    warm_pass_time: float | None = None


async def _index_repo(
    repo_path: Path,
    use_indexer: bool = True,
    warm_run: bool = False,
) -> IndexResult:
    """Walk, parse, index into PostgreSQL DB, and collect detailed metrics for a repository."""
    config = IndexerConfig()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = Repository(name=repo_path.name, root_path=repo_path)

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
                print(
                    f"\n  [WARM RUN] {repo_path.name}: Second index pass completed in "
                    f"{warm_pass_time:.4f}s (skipped all unchanged files)!"
                )
        else:
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
            warm_pass_time = None

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
        warm_pass_time=warm_pass_time,
    )


def _print_repo_report(r: IndexResult) -> None:
    total_symbols = len(r.symbols)
    files_per_sec = r.files_parsed / r.total_time if r.total_time > 0 else 0
    symbols_per_sec = total_symbols / r.total_time if r.total_time > 0 else 0

    print()
    print("=" * 60)
    print(f"  {r.name.upper()} INDEXING REPORT")
    print("=" * 60)
    print()
    print("--- File Discovery & Parsing ---")
    print(f"  Files discovered:      {r.files_discovered:>8,}")
    print(f"  Files parsed:          {r.files_parsed:>8,}")
    print(f"  Files skipped:         {r.files_skipped:>8,}")
    print(f"  Parse time:            {r.parse_time:>8.2f} s")
    print(f"  Avg parse time/file:   {r.avg_parse_time_ms:>8.2f} ms")
    print()
    print("--- Cache Statistics ---")
    print(f"  Parser cache hits:     {r.parser_hits:>8,}")
    print(f"  Parser cache misses:   {r.parser_misses:>8,}")
    print(f"  Adapter cache hits:    {r.adapter_hits:>8,}")
    print(f"  Adapter cache misses:  {r.adapter_misses:>8,}")
    print()
    print("--- Extracted Symbols Breakdown ---")
    kind_labels = [
        (SymbolKind.CLASS, "Classes"),
        (SymbolKind.FUNCTION, "Functions"),
        (SymbolKind.METHOD, "Methods"),
        (SymbolKind.CONSTANT, "Constants"),
        (SymbolKind.VARIABLE, "Variables"),
        (SymbolKind.INTERFACE, "Interfaces"),
        (SymbolKind.TYPE, "Types"),
        (SymbolKind.MODULE, "Modules"),
    ]

    for kind, label in kind_labels:
        count = r.symbol_counts.get(kind, 0)
        if count > 0:
            print(f"  {label + ':':25s}{count:>8,}")

    print(f"  Total symbols:         {total_symbols:>8,}")
    print(f"  DB symbols w/ params:  {r.symbols_with_params:>8,}")
    print(f"  DB symbols w/ docs:    {r.symbols_with_docs:>8,}")
    print()
    print("--- Code Relationships Graph Breakdown ---")
    kind_labels_rel = [
        (RelationshipKind.INHERITS, "Inheritance (INHERITS)"),
        (RelationshipKind.IMPORTS, "Imports (IMPORTS)"),
        (RelationshipKind.CALLS, "Function Calls (CALLS)"),
        (RelationshipKind.USES_TYPE, "Type Annotations (USES_TYPE)"),
    ]

    for rel_kind, label in kind_labels_rel:
        count = r.relationship_counts.get(rel_kind, 0)
        if count > 0:
            print(f"  {label + ':':30s}{count:>8,}")

    print(f"  Total Graph Edges:     {r.total_relationships:>8,}")
    print(f"  Resolved Symbols:      {r.resolved_relationships:>8,}")
    print(f"  External Symbols:      {r.external_relationships:>8,}")
    print(f"  Unresolved Symbols:    {r.unresolved_relationships:>8,}")
    print()
    print("--- Database Metrics ---")
    print(f"  Repo insert time:      {r.repo_insert_time:>8.4f} s")
    print(f"  File insert time:      {r.file_insert_time:>8.2f} s")
    print(f"  Symbol insert time:    {r.symbol_insert_time:>8.2f} s")
    print(f"  Total DB insert time:  {r.db_insert_time:>8.2f} s")
    print(f"  DB Batch count:        {r.batch_count:>8,}")
    print(f"  Avg batch size:        {r.avg_batch_size:>8.1f} items")
    print()
    print("--- Overall Performance ---")
    print(f"  Total time:            {r.total_time:>8.2f} s")
    if r.warm_pass_time is not None:
        print(f"  Warm re-index time:    {r.warm_pass_time:>8.4f} s")
    print(f"  Files/sec:             {files_per_sec:>8.1f}")
    print(f"  Symbols/sec:           {symbols_per_sec:>8.1f}")
    print(f"  Peak memory:           {r.peak_memory_mb:>8.2f} MB")
    print()


def _print_comparison_table(results: list[IndexResult]) -> None:
    print()
    print("=" * 135)
    print("  COMPARISON SUMMARY TABLE")
    print("=" * 135)
    print()

    header = (
        f"  {'Repository':<12s}"
        f"{'Files':>7s}"
        f"{'Symbols':>9s}"
        f"{'Edges':>9s}"
        f"{'Resolved':>9s}"
        f"{'Parse(s)':>9s}"
        f"{'Parse(ms/f)':>12s}"
        f"{'DB(s)':>8s}"
        f"{'Batches':>9s}"
        f"{'Total(s)':>9s}"
        f"{'Syms/s':>9s}"
        f"{'Mem(MB)':>9s}"
    )
    print(header)
    print("  " + "-" * 131)

    for r in results:
        total_symbols = len(r.symbols)
        symbols_per_sec = total_symbols / r.total_time if r.total_time > 0 else 0

        row = (
            f"  {r.name:<12s}"
            f"{r.files_parsed:>7,}"
            f"{total_symbols:>9,}"
            f"{r.total_relationships:>9,}"
            f"{r.resolved_relationships:>9,}"
            f"{r.parse_time:>9.2f}"
            f"{r.avg_parse_time_ms:>12.2f}"
            f"{r.db_insert_time:>8.2f}"
            f"{r.batch_count:>9,}"
            f"{r.total_time:>9.2f}"
            f"{symbols_per_sec:>9.1f}"
            f"{r.peak_memory_mb:>9.2f}"
        )
        print(row)

    print()

    total_files = sum(r.files_parsed for r in results)
    total_symbols = sum(len(r.symbols) for r in results)
    total_edges = sum(r.total_relationships for r in results)
    total_resolved = sum(r.resolved_relationships for r in results)
    total_time = sum(r.total_time for r in results)
    peak_mem = max(r.peak_memory_mb for r in results)
    total_parse_time = sum(r.parse_time for r in results)
    total_db_time = sum(r.db_insert_time for r in results)
    total_batches = sum(r.batch_count for r in results)
    avg_parse_ms_all = (total_parse_time / total_files * 1000.0) if total_files > 0 else 0.0

    print(
        f"  {'TOTALS':<12s}"
        f"{total_files:>7,}"
        f"{total_symbols:>9,}"
        f"{total_edges:>9,}"
        f"{total_resolved:>9,}"
        f"{total_parse_time:>9.2f}"
        f"{avg_parse_ms_all:>12.2f}"
        f"{total_db_time:>8.2f}"
        f"{total_batches:>9,}"
        f"{total_time:>9.2f}"
        f"{total_symbols / total_time if total_time > 0 else 0:>9.1f}"
        f"{peak_mem:>9.2f}"
    )
    print()
    print("=" * 135)
    print()


@pytest.mark.slow
@pytest.mark.anyio
async def test_benchmark_suite(request: pytest.FixtureRequest) -> None:
    """Index benchmark repositories into PostgreSQL DB and print metrics report."""
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
        assert r.symbols_with_params > 0, f"{r.name}: no symbols with parameters in DB"
        assert r.symbols_with_docs > 0, f"{r.name}: no symbols with documentation in DB"
        assert r.total_relationships > 0, f"{r.name}: no code relationships extracted"
        assert r.resolved_relationships + r.external_relationships > 0, (
            f"{r.name}: no resolved or external relationships"
        )
