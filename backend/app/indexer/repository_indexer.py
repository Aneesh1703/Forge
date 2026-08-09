import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import (
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.batching import batch_items
from app.indexer.config import IndexerConfig
from app.parser.adapters.adapter_factory import AdapterFactory
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol
from app.parser.parser_factory import ParserFactory
from app.repository.language import Language
from app.repository.models import Repository, RepositoryFile
from app.repository.walker import RepositoryWalker


class RepositoryIndexer:
    def __init__(
        self,
        db_session: AsyncSession,
        repository_repo: RepositoryRepository,
        file_repo: RepositoryFileRepository,
        symbol_repo: CodeSymbolRepository,
        config: IndexerConfig = IndexerConfig(),
    ) -> None:
        self._session = db_session
        self._repository_repo = repository_repo
        self._file_repo = file_repo
        self._symbol_repo = symbol_repo
        self._config = config
        self._parser_factory = ParserFactory()
        self._adapter_factory = AdapterFactory()

    async def index(self, repository: Repository) -> None:
        root_path = repository.root_path
        if not root_path:
            raise ValueError("Repository root path is not set")
        if not root_path.exists():
            raise FileNotFoundError(f"Repository root path not found: {root_path}")

        repo = self._build_repository(repository)
        files = self._collect_repository_files(repo)
        symbols = await self._parse_repository(files)

        async with self._session.begin():
            await self._store_repository(repo)
            await self._store_files(files)
            await self._store_symbols(symbols)
            await self._update_index_timestamp(repo)

    def _build_repository(self, repository: Repository) -> Repository:
        """
        Responsibilities:
        → Preserve existing repository attributes (id, git_url, default_branch)
        → Return new Repository with populated name if empty
        """
        if repository.name:
            return repository

        return Repository(
            id=repository.id,
            name=repository.root_path.name or repository.root_path.stem,
            root_path=repository.root_path,
            git_url=repository.git_url,
            default_branch=repository.default_branch,
            indexed_at=repository.indexed_at,
        )

    def _collect_repository_files(self, repo: Repository) -> list[RepositoryFile]:
        """
        Responsibilities:
        → Call RepositoryWalker
        → Walk the repository
        → Return all discovered files
        """
        walker = RepositoryWalker()
        return walker.walk(repo)

    def _parse_file(self, file: RepositoryFile) -> list[CodeSymbol]:
        """
        Parse a single file and extract code symbols synchronously.
        Skips files exceeding the configured max file size or unknown languages.
        """
        if file.size > self._config.max_file_size_bytes or file.language == Language.UNKNOWN:
            return []

        try:
            parser = self._parser_factory.get_parser(file.language)
            adapter = self._adapter_factory.get_adapter(file.language)

            result = parser.parse(file)
            extractor = SymbolExtractor(adapter)

            return extractor.extract(
                tree=result.tree,
                repository_file=file,
                source=result.source,
            )
        except ValueError as exc:
            if "Unsupported language" in str(exc):
                return []
            raise

    async def _parse_repository(
        self,
        files: list[RepositoryFile],
    ) -> list[CodeSymbol]:
        """
        Parse repository files in parallel using worker threads and extract code symbols.
        """
        if not files:
            return []

        semaphore = asyncio.Semaphore(self._config.max_workers)

        async def _parse_worker(file: RepositoryFile) -> list[CodeSymbol]:
            async with semaphore:
                return await asyncio.to_thread(self._parse_file, file)

        symbol_batches = await asyncio.gather(*(_parse_worker(file) for file in files))

        return [symbol for batch in symbol_batches for symbol in batch]

    async def _store_symbols(self, symbols: list[CodeSymbol]) -> None:
        if not symbols:
            return
        for batch in batch_items(symbols, self._config.batch_size):
            await self._symbol_repo.bulk_create(batch)

    async def _store_repository(self, repository: Repository) -> None:
        if not repository:
            return
        await self._repository_repo.create(repository)

    async def _store_files(self, files: list[RepositoryFile]) -> None:
        if not files:
            return
        for batch in batch_items(files, self._config.batch_size):
            await self._file_repo.bulk_create(batch)

    async def _update_index_timestamp(self, repository: Repository) -> None:
        if not repository:
            return

        await self._repository_repo.update_indexed_at(
            repository.id,
            datetime.now(timezone.utc),
        )
