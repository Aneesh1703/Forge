"""
Global Pytest Configuration and CLI options.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--repo",
        action="store",
        default="all",
        help="Comma-separated list of repos to benchmark (e.g., pydantic,django or all)",
    )
    parser.addoption(
        "--use-indexer",
        action="store_true",
        default=False,
        help="Run benchmark using the high-level RepositoryIndexer.index pipeline",
    )
    parser.addoption(
        "--warm-run",
        action="store_true",
        default=False,
        help="Run a second warm indexing pass to benchmark incremental speed",
    )
