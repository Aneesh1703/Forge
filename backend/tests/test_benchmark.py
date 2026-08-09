import math
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.db.database import engine, session_factory
from app.db.models.base import Base
from app.db.repositories import (
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.config import IndexerConfig
from app.indexer.repository_indexer import RepositoryIndexer
from app.parser.models import CodeSymbol, SymbolKind
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


async def _index_repo(repo_path: Path) -> IndexResult:
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

        indexer = RepositoryIndexer(
            db_session=session,
            repository_repo=repo_repo,
            file_repo=file_repo,
            symbol_repo=symbol_repo,
            config=config,
        )

        files = indexer._collect_repository_files(repo)
        files_discovered = len(files)

        parse_start = time.perf_counter()
        symbols = await indexer._parse_repository(files)
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

            await indexer._update_index_timestamp(repo)

        db_insert_time = time.perf_counter() - db_start

    total_time = time.perf_counter() - total_start

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak / (1024 * 1024)

    parsed_files = [f for f in files if f.size <= config.max_file_size_bytes]
    skipped_count = len(files) - len(parsed_files)
    parsed_len = len(parsed_files)

    avg_parse_ms = (parse_time / parsed_len * 1000.0) if parsed_len > 0 else 0.0

    file_batches = math.ceil(len(files) / config.batch_size) if files else 0
    symbol_batches = math.ceil(len(symbols) / config.batch_size) if symbols else 0
    batch_count = file_batches + symbol_batches
    total_items = len(files) + len(symbols)
    avg_batch_size = (total_items / batch_count) if batch_count > 0 else 0.0

    counts: Counter[SymbolKind] = Counter()
    for sym in symbols:
        counts[sym.kind] += 1

    return IndexResult(
        name=repo_path.name,
        files_discovered=files_discovered,
        files_parsed=parsed_len,
        files_skipped=skipped_count,
        symbols=symbols,
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
    print(f"  Files/sec:             {files_per_sec:>8.1f}")
    print(f"  Symbols/sec:           {symbols_per_sec:>8.1f}")
    print(f"  Peak memory:           {r.peak_memory_mb:>8.2f} MB")
    print()


def _print_comparison_table(results: list[IndexResult]) -> None:
    print()
    print("=" * 115)
    print("  COMPARISON SUMMARY TABLE")
    print("=" * 115)
    print()

    header = (
        f"  {'Repository':<12s}"
        f"{'Files':>7s}"
        f"{'Symbols':>9s}"
        f"{'Parse(s)':>9s}"
        f"{'Parse(ms/f)':>12s}"
        f"{'DB(s)':>8s}"
        f"{'Batches':>9s}"
        f"{'Total(s)':>9s}"
        f"{'Syms/s':>9s}"
        f"{'Mem(MB)':>9s}"
    )
    print(header)
    print("  " + "-" * 111)

    for r in results:
        total_symbols = len(r.symbols)
        symbols_per_sec = total_symbols / r.total_time if r.total_time > 0 else 0

        row = (
            f"  {r.name:<12s}"
            f"{r.files_parsed:>7,}"
            f"{total_symbols:>9,}"
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
        f"{total_parse_time:>9.2f}"
        f"{avg_parse_ms_all:>12.2f}"
        f"{total_db_time:>8.2f}"
        f"{total_batches:>9,}"
        f"{total_time:>9.2f}"
        f"{total_symbols / total_time if total_time > 0 else 0:>9.1f}"
        f"{peak_mem:>9.2f}"
    )
    print()
    print("=" * 115)
    print()


@pytest.mark.slow
@pytest.mark.anyio
async def test_benchmark_suite() -> None:
    """Index all benchmark repositories into PostgreSQL DB and print metrics report."""

    missing = [name for name in REPOS if not (BENCHMARKS_DIR / name).exists()]
    if missing:
        pytest.skip(
            f"Benchmark repos not found: {', '.join(missing)}. Clone them into {BENCHMARKS_DIR}"
        )

    results: list[IndexResult] = []

    for repo_name in REPOS:
        repo_path = BENCHMARKS_DIR / repo_name
        result = await _index_repo(repo_path)
        _print_repo_report(result)
        results.append(result)

    _print_comparison_table(results)

    for r in results:
        assert r.files_discovered > 0, f"{r.name}: no files discovered"
        assert r.files_parsed > 0, f"{r.name}: no files parsed"
        assert len(r.symbols) > 0, f"{r.name}: no symbols extracted"
