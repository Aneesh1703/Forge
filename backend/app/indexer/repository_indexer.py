import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RepositoryFileORM
from app.db.repositories import (
    CodeRelationshipRepository,
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.batching import batch_items
from app.indexer.config import IndexerConfig
from app.indexer.vector_indexer import IncrementalVectorIndexer
from app.orchestration.workflow import ForgeStateGraph
from app.parser.adapters.adapter_factory import AdapterFactory
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol
from app.parser.parser_factory import ParserFactory
from app.relationships import RawRelationship, SymbolResolver
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
        relationship_repo: CodeRelationshipRepository | None = None,
        config: IndexerConfig = IndexerConfig(),
        vector_indexer: IncrementalVectorIndexer | None = None,
    ) -> None:
        self._session = db_session
        self._repository_repo = repository_repo
        self._file_repo = file_repo
        self._symbol_repo = symbol_repo
        self._relationship_repo = relationship_repo or CodeRelationshipRepository(db_session)
        self._config = config
        self._vector_indexer = vector_indexer
        self._parser_factory = ParserFactory()
        self._adapter_factory = AdapterFactory()

    async def index_with_graph(self, repository: Repository) -> None:
        """Executes repository indexing via stateful LangGraph StateGraph DAG execution."""
        sg: ForgeStateGraph[Any] = ForgeStateGraph()
        sg.add_node("index", lambda state: state)
        await self.index(repository)

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

        symbols, raw_relationships = await self._parse_repository(files_to_parse)

        await self._persist_index(
            existing_repo is not None,
            repo,
            stale_file_ids,
            files_to_insert,
            symbols,
            raw_relationships,
            files_to_parse,
        )

    async def _persist_index(
        self,
        repo_exists: bool,
        repo: Repository,
        stale_file_ids: list[UUID],
        files_to_insert: list[RepositoryFile],
        symbols: list[CodeSymbol],
        raw_relationships: list[RawRelationship],
        parsed_files: list[RepositoryFile] | None = None,
    ) -> None:
        if not repo_exists:
            await self._store_repository(repo)

        if stale_file_ids:
            await self._relationship_repo.delete_by_file_ids(stale_file_ids)
            await self._symbol_repo.delete_by_file_ids(stale_file_ids)
            await self._file_repo.delete_by_ids(stale_file_ids)

        if files_to_insert:
            await self._store_files(files_to_insert)

        if symbols:
            await self._store_symbols(symbols)

        if raw_relationships:
            await self._resolve_and_store_relationships(repo.id, symbols, raw_relationships)

        if self._vector_indexer is not None:
            await self._vector_indexer.sync_incremental(
                repository_id=repo.id,
                stale_file_ids=stale_file_ids,
                parsed_files=parsed_files or [],
                symbols=symbols,
            )

        await self._update_index_timestamp(repo)
        await self._session.commit()

    async def _resolve_and_store_relationships(
        self,
        repository_id: UUID,
        symbols: list[CodeSymbol],
        raw_relationships: list[RawRelationship],
    ) -> None:
        symbols_by_id = {s.id: s for s in symbols}
        symbols_by_qualname = {s.qualified_name: s for s in symbols if s.qualified_name}
        symbols_by_name: dict[str, list[CodeSymbol]] = {}
        for s in symbols:
            symbols_by_name.setdefault(s.name, []).append(s)

        resolver = SymbolResolver()
        raw_by_file: dict[UUID, list[RawRelationship]] = {}
        for r in raw_relationships:
            raw_by_file.setdefault(r.source_file_id, []).append(r)

        file_symbols_map: dict[UUID, list[CodeSymbol]] = {}
        for s in symbols:
            file_symbols_map.setdefault(s.file.id, []).append(s)

        all_resolved = []
        for file_id, raw_list in raw_by_file.items():
            f_syms = file_symbols_map.get(file_id, [])
            resolved = resolver.resolve_relationships(
                repository_id=repository_id,
                file_id=file_id,
                raw_relationships=raw_list,
                symbols_by_id=symbols_by_id,
                symbols_by_qualname=symbols_by_qualname,
                symbols_by_name=symbols_by_name,
                file_symbols=f_syms,
            )
            all_resolved.extend(resolved)

        if all_resolved:
            for batch in batch_items(all_resolved, self._config.batch_size):
                await self._relationship_repo.bulk_create(batch)

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
        walker = RepositoryWalker()
        return walker.walk(repo)

    def _parse_file(self, file: RepositoryFile) -> tuple[list[CodeSymbol], list[RawRelationship]]:
        if file.size > self._config.max_file_size_bytes or file.language == Language.UNKNOWN:
            return [], []

        try:
            parser = self._parser_factory.get_parser(file.language)
            adapter = self._adapter_factory.get_adapter(file.language)

            result = parser.parse(file)
            extractor = SymbolExtractor(adapter)

            return extractor.extract_with_relationships(
                tree=result.tree,
                repository_file=file,
                source=result.source,
            )
        except ValueError as exc:
            if "Unsupported language" in str(exc):
                return [], []
            raise

    async def _parse_repository(
        self,
        files: list[RepositoryFile],
    ) -> tuple[list[CodeSymbol], list[RawRelationship]]:
        if not files:
            return [], []

        semaphore = asyncio.Semaphore(self._config.max_workers)

        async def _parse_worker(
            file: RepositoryFile,
        ) -> tuple[list[CodeSymbol], list[RawRelationship]]:
            async with semaphore:
                return await asyncio.to_thread(self._parse_file, file)

        results = await asyncio.gather(*(_parse_worker(file) for file in files))

        symbols = [s for sym_batch, _ in results for s in sym_batch]
        raw_rels = [r for _, rel_batch in results for r in rel_batch]

        return symbols, raw_rels

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
