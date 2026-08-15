"""
Batch Size Benchmarking Suite for PostgreSQL DB Persistence.

Evaluates PostgreSQL batch insertion throughput (symbols/sec) and DB write latency
across batch sizes [50, 100, 250, 500, 1000].
"""

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.db.database import engine, session_factory
from app.db.models.base import Base
from app.db.repositories import (
    CodeRelationshipRepository,
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.config import IndexerConfig
from app.indexer.repository_indexer import RepositoryIndexer
from app.repository.models import Repository


@dataclass
class BatchResult:
    batch_size: int
    total_files: int
    total_symbols: int
    file_insert_s: float
    symbol_insert_s: float
    total_db_s: float
    total_batches: int
    symbols_per_sec: float


@pytest.mark.anyio
async def test_benchmark_batch_sizes() -> None:
    test_repo_path = Path("d:/benchmarks/pydantic")
    if not test_repo_path.exists():
        pytest.skip(f"Test repo not found: {test_repo_path}")

    batch_sizes = [50, 100, 250, 500, 1000]
    results: list[BatchResult] = []

    print("\n" + "=" * 80)
    print("  POSTGRESQL BATCH SIZE BENCHMARK (PYDANTIC REPOSITORY)")
    print("=" * 80)

    for b_size in batch_sizes:
        # Reset DB tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        config = IndexerConfig(batch_size=b_size)

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

            repo = indexer._build_repository(Repository(name="Pydantic", root_path=test_repo_path))
            files = indexer._collect_repository_files(repo)
            symbols, _ = await indexer._parse_repository(files)

            # Measure DB insertion times
            t_db_start = time.perf_counter()

            async with session.begin():
                await indexer._store_repository(repo)

                t_f_start = time.perf_counter()
                await indexer._store_files(files)
                t_f_end = time.perf_counter()

                t_s_start = time.perf_counter()
                await indexer._store_symbols(symbols)
                t_s_end = time.perf_counter()

            t_db_end = time.perf_counter()

            f_time = t_f_end - t_f_start
            s_time = t_s_end - t_s_start
            total_db_time = t_db_end - t_db_start

            num_file_batches = (len(files) + b_size - 1) // b_size if files else 0
            num_symbol_batches = (len(symbols) + b_size - 1) // b_size if symbols else 0
            total_batches = num_file_batches + num_symbol_batches

            throughput = len(symbols) / total_db_time if total_db_time > 0 else 0

            res = BatchResult(
                batch_size=b_size,
                total_files=len(files),
                total_symbols=len(symbols),
                file_insert_s=f_time,
                symbol_insert_s=s_time,
                total_db_s=total_db_time,
                total_batches=total_batches,
                symbols_per_sec=throughput,
            )
            results.append(res)
            print(
                f"Batch Size {b_size:4d} | DB Time: {total_db_time:6.2f}s | "
                f"Batches: {total_batches:4d} | Throughput: {throughput:7.1f} syms/sec"
            )

    print("\n" + "=" * 90)
    print("  BATCH SIZE COMPARISON SUMMARY")
    print("=" * 90)
    print(
        f"  {'Batch Size':<12} {'File Ins(s)':<12} {'Sym Ins(s)':<12} "
        f"{'Total DB(s)':<14} {'Batches':<10} {'Syms/sec':<12}"
    )
    print("  " + "-" * 86)
    for r in results:
        print(
            f"  {r.batch_size:<12d} {r.file_insert_s:<12.3f} "
            f"{r.symbol_insert_s:<12.3f} {r.total_db_s:<14.3f} "
            f"{r.total_batches:<10d} {r.symbols_per_sec:<12.1f}"
        )
    print("=" * 90 + "\n")
