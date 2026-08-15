import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepositoryFileORM
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

        existing_repo = await self._repository_repo.get_existing(repository)
        if existing_repo:
            repo = Repository(
                id=existing_repo.id,
                name=repository.name or existing_repo.name,
                root_path=repository.root_path,
                git_url=repository.git_url or existing_repo.git_url,
                git_url_normalized=existing_repo.git_url_normalized,
                default_branch=repository.default_branch or existing_repo.default_branch,
                indexed_at=existing_repo.indexed_at,
            )
        else:
            repo = self._build_repository(repository)

        discovered_files = self._collect_repository_files(repo)
        existing_files = await self._file_repo.get_by_repository(repo.id)
        db_files_map = {f.relative_path: f for f in existing_files}

        files_to_parse, files_to_insert, stale_file_ids = self._diff_files(
            discovered_files, db_files_map
        )

        symbols = await self._parse_repository(files_to_parse)

        await self._persist_index(
            existing_repo is not None,
            repo,
            stale_file_ids,
            files_to_insert,
            symbols,
        )

    async def _persist_index(
        self,
        repo_exists: bool,
        repo: Repository,
        stale_file_ids: list[UUID],
        files_to_insert: list[RepositoryFile],
        symbols: list[CodeSymbol],
    ) -> None:
        if not repo_exists:
            await self._store_repository(repo)

        if stale_file_ids:
            await self._symbol_repo.delete_by_file_ids(stale_file_ids)
            await self._file_repo.delete_by_ids(stale_file_ids)

        if files_to_insert:
            await self._store_files(files_to_insert)

        if symbols:
            await self._store_symbols(symbols)

        await self._update_index_timestamp(repo)
        await self._session.commit()

    def _diff_files(
        self,
        discovered_files: list[RepositoryFile],
        db_files_map: dict[str, RepositoryFileORM],
    ) -> tuple[list[RepositoryFile], list[RepositoryFile], list[UUID]]:
        files_to_parse: list[RepositoryFile] = []
        files_to_insert: list[RepositoryFile] = []
        stale_file_ids: list[UUID] = []
        discovered_paths = set()

        for disc_file in discovered_files:
            rel_str = str(disc_file.relative_path)
            discovered_paths.add(rel_str)
            db_file = db_files_map.get(rel_str)

            if db_file is None:
                files_to_parse.append(disc_file)
                files_to_insert.append(disc_file)
            else:
                is_changed = False
                if disc_file.content_hash and db_file.hash:
                    if disc_file.content_hash != db_file.hash:
                        is_changed = True
                elif disc_file.size != db_file.size:
                    is_changed = True

                if is_changed:
                    disc_file.id = db_file.id
                    stale_file_ids.append(db_file.id)
                    files_to_parse.append(disc_file)
                    files_to_insert.append(disc_file)

        for rel_str, db_file in db_files_map.items():
            if rel_str not in discovered_paths:
                stale_file_ids.append(db_file.id)

        return files_to_parse, files_to_insert, stale_file_ids

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
