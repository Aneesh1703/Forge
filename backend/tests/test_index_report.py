"""
Integration test that walks, parses, and produces an indexing report.

Runs against the Forge repository root (../../) without touching the database.
Prints a formatted summary of discovered files, parsed files, skipped files,
and symbol counts broken down by kind.
"""

import time
from collections import Counter
from pathlib import Path

import pytest

from app.parser.adapters.adapter_factory import AdapterFactory
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol, SymbolKind
from app.parser.parser_factory import ParserFactory
from app.repository.models import Repository
from app.repository.walker import RepositoryWalker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _print_report(
    repo_name: str,
    total_files: int,
    parsed_files: int,
    skipped_files: int,
    symbol_counts: Counter[SymbolKind],
    elapsed: float,
) -> None:
    total_symbols = sum(symbol_counts.values())

    print()
    print("=" * 36)
    print("Forge Indexing Report")
    print("=" * 36)
    print()
    print("Repository:")
    print(f"    {repo_name}")
    print()
    print("Files discovered:")
    print(f"    {total_files}")
    print()
    print("Files parsed:")
    print(f"    {parsed_files}")
    print()
    print("Skipped:")
    print(f"    {skipped_files}")
    print()

    kind_labels = {
        SymbolKind.CLASS: "Classes",
        SymbolKind.FUNCTION: "Functions",
        SymbolKind.METHOD: "Methods",
        SymbolKind.CONSTANT: "Constants",
        SymbolKind.VARIABLE: "Variables",
        SymbolKind.INTERFACE: "Interfaces",
        SymbolKind.TYPE: "Types",
        SymbolKind.NAMESPACE: "Namespaces",
        SymbolKind.MODULE: "Modules",
        SymbolKind.UNKNOWN: "Unknown",
    }

    for kind, label in kind_labels.items():
        count = symbol_counts.get(kind, 0)
        if count > 0:
            print(f"{label}:")
            print(f"    {count}")
            print()

    print("Total symbols:")
    print(f"    {total_symbols}")
    print()
    print("Index completed in:")
    print(f"    {elapsed:.2f} seconds")
    print()


@pytest.mark.slow
def test_index_report() -> None:
    """Walk the Forge repository, parse all supported files, and print a report."""

    parser_factory = ParserFactory()
    adapter_factory = AdapterFactory()

    repo = Repository(name=REPO_ROOT.name, root_path=REPO_ROOT)
    walker = RepositoryWalker()

    start = time.perf_counter()

    files = walker.walk(repo)
    total_files = len(files)

    parsed_files = 0
    skipped_files = 0
    all_symbols: list[CodeSymbol] = []

    for file in files:
        try:
            parser = parser_factory.get_parser(file.language)
            adapter = adapter_factory.get_adapter(file.language)

            result = parser.parse(file)
            extractor = SymbolExtractor(adapter)

            symbols = extractor.extract(
                tree=result.tree,
                repository_file=file,
                source=result.source,
            )

            all_symbols.extend(symbols)
            parsed_files += 1

        except ValueError as exc:
            if "Unsupported language" in str(exc):
                skipped_files += 1
                continue
            raise

    elapsed = time.perf_counter() - start

    symbol_counts: Counter[SymbolKind] = Counter()
    for symbol in all_symbols:
        symbol_counts[symbol.kind] += 1

    _print_report(
        repo_name=repo.name,
        total_files=total_files,
        parsed_files=parsed_files,
        skipped_files=skipped_files,
        symbol_counts=symbol_counts,
        elapsed=elapsed,
    )

    assert total_files > 0, "No files discovered"
    assert parsed_files > 0, "No files were parsed"
    assert len(all_symbols) > 0, "No symbols extracted"
