"""
Comprehensive Integration Test Suite for Forge Phase 4 Query & Context Layer.
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest

from app.db.database import engine, session_factory
from app.db.models.base import Base
from app.db.models.code_relationship_orm import CodeRelationshipORM
from app.db.models.code_symbol_orm import CodeSymbolORM
from app.db.models.repository_file_orm import RepositoryFileORM
from app.db.models.repository_orm import RepositoryORM
from app.parser.models import SymbolKind
from app.query import (
    GraphQueryService,
    ImpactQueryService,
    RepositoryContextBuilder,
    RepositoryQueryService,
    SymbolQueryFilter,
    SymbolQueryService,
)
from app.relationships.models import RelationshipKind, ResolutionStatus


@pytest.fixture
async def setup_db() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.anyio
async def test_phase4_query_engine(setup_db: None) -> None:
    async with session_factory() as session:
        # 1. Create Repository
        repo_id = uuid.uuid4()
        repo = RepositoryORM(
            id=repo_id,
            name="TestRepo",
            root_path="/path/to/repo",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(repo)

        # 2. Create Files
        file1_id = uuid.uuid4()
        file1 = RepositoryFileORM(
            id=file1_id,
            repository_id=repo_id,
            relative_path="app/auth.py",
            absolute_path="/path/to/repo/app/auth.py",
            language="python",
            extension=".py",
            size=1024,
            hash="abc123hash",
            last_modified=datetime.now(timezone.utc),
        )
        file2_id = uuid.uuid4()
        file2 = RepositoryFileORM(
            id=file2_id,
            repository_id=repo_id,
            relative_path="app/service.py",
            absolute_path="/path/to/repo/app/service.py",
            language="python",
            extension=".py",
            size=2048,
            hash="def456hash",
            last_modified=datetime.now(timezone.utc),
        )
        session.add_all([file1, file2])

        # 3. Create Symbols
        parent_class_id = uuid.uuid4()
        parent_class = CodeSymbolORM(
            id=parent_class_id,
            file_id=file1_id,
            name="BaseAuth",
            kind=SymbolKind.CLASS.value,
            qualified_name="app.auth.BaseAuth",
            start_line=5,
            end_line=20,
            start_column=0,
            end_column=15,
            start_byte=100,
            end_byte=500,
            visibility="public",
        )

        child_method_id = uuid.uuid4()
        child_method = CodeSymbolORM(
            id=child_method_id,
            file_id=file1_id,
            parent_symbol_id=parent_class_id,
            name="authenticate",
            kind=SymbolKind.METHOD.value,
            qualified_name="app.auth.BaseAuth.authenticate",
            start_line=10,
            end_line=18,
            start_column=4,
            end_column=20,
            start_byte=200,
            end_byte=450,
            visibility="public",
            documentation="Authenticates user credentials.",
        )

        caller_fn_id = uuid.uuid4()
        caller_fn = CodeSymbolORM(
            id=caller_fn_id,
            file_id=file2_id,
            name="login_handler",
            kind=SymbolKind.FUNCTION.value,
            qualified_name="app.service.login_handler",
            start_line=1,
            end_line=15,
            start_column=0,
            end_column=25,
            start_byte=0,
            end_byte=300,
            visibility="public",
        )

        session.add_all([parent_class, child_method, caller_fn])

        # 4. Create Relationships
        # caller_fn CALLS child_method
        rel_call = CodeRelationshipORM(
            id=uuid.uuid4(),
            repository_id=repo_id,
            file_id=file2_id,
            source_symbol_id=caller_fn_id,
            source_qualified_name="app.service.login_handler",
            source_line=5,
            target_symbol_id=child_method_id,
            target_name="authenticate",
            kind=RelationshipKind.CALLS.value,
            status=ResolutionStatus.RESOLVED.value,
        )

        # file2 IMPORTS file1
        rel_import = CodeRelationshipORM(
            id=uuid.uuid4(),
            repository_id=repo_id,
            file_id=file2_id,
            source_line=1,
            target_symbol_id=parent_class_id,
            target_name="BaseAuth",
            kind=RelationshipKind.IMPORTS.value,
            status=ResolutionStatus.RESOLVED.value,
        )

        session.add_all([rel_call, rel_import])
        await session.commit()

        # Instantiate Query Services
        symbol_service = SymbolQueryService(session)
        graph_service = GraphQueryService(session)
        impact_service = ImpactQueryService(session)
        repo_service = RepositoryQueryService(session)
        context_builder = RepositoryContextBuilder(session)

        # --- Test 1: SymbolQueryService ---
        filter_opts = SymbolQueryFilter(repo_id=repo_id, name="authenticate")
        results = await symbol_service.search_symbols(repo_id, filter_opts)
        assert len(results) == 1
        assert results[0].qualified_name == "app.auth.BaseAuth.authenticate"

        qual_res = await symbol_service.find_by_qualified_name(repo_id, "app.service.login_handler")
        assert qual_res is not None
        assert qual_res.name == "login_handler"

        children = await symbol_service.find_children(parent_class_id)
        assert len(children) == 1
        assert children[0].name == "authenticate"

        parent = await symbol_service.find_parent(child_method_id)
        assert parent is not None
        assert parent.name == "BaseAuth"

        # --- Test 2: GraphQueryService ---
        callers = await graph_service.get_callers(child_method_id, depth=1)
        assert len(callers.edges) == 1
        assert callers.edges[0].source_symbol_id == caller_fn_id

        callees = await graph_service.get_callees(caller_fn_id, depth=1)
        assert len(callees.edges) == 1
        assert callees.edges[0].target_symbol_id == child_method_id

        importers = await graph_service.get_importers(file1_id)
        assert len(importers) == 1
        assert importers[0].file_id == file2_id

        # --- Test 3: ImpactQueryService ---
        impact = await impact_service.get_impact_analysis(child_method_id, depth=2)
        assert impact is not None
        assert len(impact.direct_callers) == 1
        assert impact.direct_callers[0].name == "login_handler"
        assert "app/service.py" in impact.affected_file_paths

        call_path = await impact_service.find_call_path(caller_fn_id, child_method_id, max_depth=3)
        assert len(call_path) == 1
        assert call_path[0].target_symbol_id == child_method_id

        # --- Test 4: RepositoryQueryService ---
        stats = await repo_service.get_repository_statistics(repo_id)
        assert stats.total_files == 2
        assert stats.total_symbols == 3
        assert stats.total_relationships == 2

        # --- Test 5: RepositoryContextBuilder ---
        related = await context_builder.get_related_symbols(child_method_id, depth=1)
        assert len(related) >= 2  # parent (BaseAuth) + caller (login_handler)

        sym_ctx = await context_builder.build_symbol_context(repo_id, child_method_id, depth=1)
        assert sym_ctx is not None
        assert len(sym_ctx.primary_symbols) == 1
        assert sym_ctx.primary_symbols[0].name == "authenticate"
        assert "app/auth.py" in sym_ctx.relevant_files
        assert "app/service.py" in sym_ctx.relevant_files

        query_ctx = await context_builder.build_query_context(
            repo_id, "authenticate", max_symbols=5
        )
        assert len(query_ctx.primary_symbols) >= 1
        assert query_ctx.primary_symbols[0].name == "authenticate"
