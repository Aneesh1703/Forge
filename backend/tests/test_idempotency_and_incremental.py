from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.db.database import session_factory
from app.db.models import CodeSymbolORM, RepositoryFileORM, RepositoryORM
from app.db.repositories import (
    CodeSymbolRepository,
    RepositoryFileRepository,
    RepositoryRepository,
)
from app.indexer.repository_indexer import RepositoryIndexer
from app.repository.models import Repository


def test_git_url_normalization() -> None:
    norm = RepositoryRepository.normalize_git_url

    assert norm("https://github.com/fastapi/fastapi.git") == "github.com/fastapi/fastapi"
    assert norm("git@github.com:fastapi/fastapi.git") == "github.com/fastapi/fastapi"
    assert norm("HTTPS://GITHUB.COM/FASTAPI/FASTAPI/") == "github.com/fastapi/fastapi"
    assert norm("http://github.com/fastapi/fastapi") == "github.com/fastapi/fastapi"
    assert norm("ssh://git@github.com/fastapi/fastapi.git") == "github.com/fastapi/fastapi"
    assert norm("") is None
    assert norm(None) is None


@pytest.mark.anyio
async def test_repository_get_existing_cascade(tmp_path: Path) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(delete(CodeSymbolORM))
            await session.execute(delete(RepositoryFileORM))
            await session.execute(delete(RepositoryORM))

        repo_repo = RepositoryRepository(session)

        async with session.begin():
            repo1 = Repository(
                name="test-repo",
                root_path=tmp_path,
                git_url="https://github.com/owner/test1.git",
            )
            orm1 = await repo_repo.create(repo1)

        # 1. Match by ID
        query_by_id = Repository(id=orm1.id, name="different", root_path=tmp_path / "other")
        found_by_id = await repo_repo.get_existing(query_by_id)
        assert found_by_id is not None
        assert found_by_id.id == orm1.id

        # 2. Match by normalized git_url
        query_by_url = Repository(
            name="different",
            root_path=tmp_path / "other",
            git_url="git@github.com:owner/test1.git",
        )
        found_by_url = await repo_repo.get_existing(query_by_url)
        assert found_by_url is not None
        assert found_by_url.id == orm1.id

        # 3. Match by root_path
        query_by_path = Repository(name="different", root_path=tmp_path)
        found_by_path = await repo_repo.get_existing(query_by_path)
        assert found_by_path is not None
        assert found_by_path.id == orm1.id


@pytest.mark.anyio
async def test_same_repo_same_files_zero_new_records(tmp_path: Path) -> None:
    """Scenario 1: same repo, same files -> 0 new DB records."""
    file1 = tmp_path / "module_a.py"
    file1.write_text("def func_a(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    file2 = tmp_path / "module_b.py"
    file2.write_text("class ClassB:\n    def method_b(self):\n        pass\n", encoding="utf-8")

    repo_input = Repository(name="zero-records-demo", root_path=tmp_path)

    async with session_factory() as session:
        async with session.begin():
            await session.execute(delete(CodeSymbolORM))
            await session.execute(delete(RepositoryFileORM))
            await session.execute(delete(RepositoryORM))

        repo_repo = RepositoryRepository(session)
        file_repo = RepositoryFileRepository(session)
        symbol_repo = CodeSymbolRepository(session)
        indexer = RepositoryIndexer(session, repo_repo, file_repo, symbol_repo)

        # Initial index
        await indexer.index(repo_input)

        repos_v1 = (await session.scalars(select(RepositoryORM))).all()
        files_v1 = (await session.scalars(select(RepositoryFileORM))).all()
        symbols_v1 = (await session.scalars(select(CodeSymbolORM))).all()

        count_repos_v1 = len(repos_v1)
        count_files_v1 = len(files_v1)
        count_symbols_v1 = len(symbols_v1)

        # Second index run without file changes
        await indexer.index(repo_input)

        repos_v2 = (await session.scalars(select(RepositoryORM))).all()
        files_v2 = (await session.scalars(select(RepositoryFileORM))).all()
        symbols_v2 = (await session.scalars(select(CodeSymbolORM))).all()

        assert len(repos_v2) == count_repos_v1
        assert len(files_v2) == count_files_v1
        assert len(symbols_v2) == count_symbols_v1
        assert {f.id for f in files_v2} == {f.id for f in files_v1}
        assert {s.id for s in symbols_v2} == {s.id for s in symbols_v1}


@pytest.mark.anyio
async def test_modify_one_file_reparse_and_replace_symbols(tmp_path: Path) -> None:
    """Scenario 2: modify one file -> only 1 reparsed, symbols replaced, unchanged untouched."""
    file1 = tmp_path / "module_a.py"
    file1.write_text("def func_a(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    file2 = tmp_path / "module_b.py"
    file2.write_text("class ClassB:\n    def method_b(self):\n        pass\n", encoding="utf-8")

    repo_input = Repository(name="modify-one-file-demo", root_path=tmp_path)

    async with session_factory() as session:
        async with session.begin():
            await session.execute(delete(CodeSymbolORM))
            await session.execute(delete(RepositoryFileORM))
            await session.execute(delete(RepositoryORM))

        repo_repo = RepositoryRepository(session)
        file_repo = RepositoryFileRepository(session)
        symbol_repo = CodeSymbolRepository(session)
        indexer = RepositoryIndexer(session, repo_repo, file_repo, symbol_repo)

        await indexer.index(repo_input)

        all_files_v1 = (await session.scalars(select(RepositoryFileORM))).all()
        files_v1 = {f.relative_path: f for f in all_files_v1}
        symbols_v1_file2 = (
            await session.scalars(
                select(CodeSymbolORM).where(CodeSymbolORM.file_id == files_v1["module_b.py"].id)
            )
        ).all()
        file2_updated_at_v1 = files_v1["module_b.py"].updated_at

        # Modify module_a.py only
        file1.write_text(
            "def func_a(x: int, y: int, z: int) -> int:\n    return x + y + z\n", encoding="utf-8"
        )

        await indexer.index(repo_input)

        all_files_v2 = (await session.scalars(select(RepositoryFileORM))).all()
        files_v2 = {f.relative_path: f for f in all_files_v2}

        # Unchanged file module_b.py remains untouched
        assert files_v2["module_b.py"].id == files_v1["module_b.py"].id
        assert files_v2["module_b.py"].hash == files_v1["module_b.py"].hash
        assert files_v2["module_b.py"].updated_at == file2_updated_at_v1

        symbols_v2_file2 = (
            await session.scalars(
                select(CodeSymbolORM).where(CodeSymbolORM.file_id == files_v2["module_b.py"].id)
            )
        ).all()
        assert {s.id for s in symbols_v2_file2} == {s.id for s in symbols_v1_file2}

        # Reparsed file module_a.py symbols replaced with new parameters
        symbols_v2_file1 = (
            await session.scalars(
                select(CodeSymbolORM).where(CodeSymbolORM.file_id == files_v2["module_a.py"].id)
            )
        ).all()
        func_a = next(s for s in symbols_v2_file1 if s.name == "func_a")
        params = func_a.parameters
        assert params is not None
        assert len(params) == 3


@pytest.mark.anyio
async def test_add_one_file_parses_only_new_file(tmp_path: Path) -> None:
    """Scenario 3: add one file -> only new file parsed."""
    file1 = tmp_path / "module_a.py"
    file1.write_text("def func_a() -> None:\n    pass\n", encoding="utf-8")

    repo_input = Repository(name="add-one-file-demo", root_path=tmp_path)

    async with session_factory() as session:
        async with session.begin():
            await session.execute(delete(CodeSymbolORM))
            await session.execute(delete(RepositoryFileORM))
            await session.execute(delete(RepositoryORM))

        repo_repo = RepositoryRepository(session)
        file_repo = RepositoryFileRepository(session)
        symbol_repo = CodeSymbolRepository(session)
        indexer = RepositoryIndexer(session, repo_repo, file_repo, symbol_repo)

        await indexer.index(repo_input)

        files_v1 = (await session.scalars(select(RepositoryFileORM))).all()
        symbols_v1 = (await session.scalars(select(CodeSymbolORM))).all()
        assert len(files_v1) == 1
        assert len(symbols_v1) == 1

        # Add module_b.py
        file2 = tmp_path / "module_b.py"
        file2.write_text("def func_b() -> int:\n    return 42\n", encoding="utf-8")

        await indexer.index(repo_input)

        files_v2 = (await session.scalars(select(RepositoryFileORM))).all()
        symbols_v2 = (await session.scalars(select(CodeSymbolORM))).all()
        assert len(files_v2) == 2
        assert len(symbols_v2) == 2

        # Original file1 record and symbol remain identical
        f1_v2 = next(f for f in files_v2 if f.relative_path == "module_a.py")
        assert f1_v2.id == files_v1[0].id

        s1_v2 = next(s for s in symbols_v2 if s.file_id == f1_v2.id)
        assert s1_v2.id == symbols_v1[0].id


@pytest.mark.anyio
async def test_delete_one_file_removes_file_and_symbols(tmp_path: Path) -> None:
    """Scenario 4: delete one file -> file + its symbols removed."""
    file1 = tmp_path / "module_a.py"
    file1.write_text("def func_a() -> None:\n    pass\n", encoding="utf-8")

    file2 = tmp_path / "module_b.py"
    file2.write_text("def func_b() -> None:\n    pass\n", encoding="utf-8")

    repo_input = Repository(name="delete-one-file-demo", root_path=tmp_path)

    async with session_factory() as session:
        async with session.begin():
            await session.execute(delete(CodeSymbolORM))
            await session.execute(delete(RepositoryFileORM))
            await session.execute(delete(RepositoryORM))

        repo_repo = RepositoryRepository(session)
        file_repo = RepositoryFileRepository(session)
        symbol_repo = CodeSymbolRepository(session)
        indexer = RepositoryIndexer(session, repo_repo, file_repo, symbol_repo)

        await indexer.index(repo_input)

        files_v1 = (await session.scalars(select(RepositoryFileORM))).all()
        symbols_v1 = (await session.scalars(select(CodeSymbolORM))).all()
        assert len(files_v1) == 2
        assert len(symbols_v1) == 2

        deleted_file_id = next(f.id for f in files_v1 if f.relative_path == "module_a.py")

        # Delete module_a.py on disk
        file1.unlink()

        await indexer.index(repo_input)

        files_v2 = (await session.scalars(select(RepositoryFileORM))).all()

        assert len(files_v2) == 1
        assert files_v2[0].relative_path == "module_b.py"

        # Verify module_a.py file record is gone
        deleted_file_record = await session.get(RepositoryFileORM, deleted_file_id)
        assert deleted_file_record is None

        # Verify all symbols linked to deleted_file_id are removed from DB
        orphan_symbols = (
            await session.scalars(
                select(CodeSymbolORM).where(CodeSymbolORM.file_id == deleted_file_id)
            )
        ).all()
        assert len(orphan_symbols) == 0
