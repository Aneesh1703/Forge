from pathlib import Path
from uuid import uuid4

from app.parser.adapters.python import PythonAdapter
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol, SymbolKind
from app.parser.parser_factory import ParserFactory
from app.relationships.models import (
    CodeRelationship,
    RawRelationship,
    RelationshipKind,
    ResolutionStatus,
)
from app.relationships.symbol_resolver import SymbolResolver
from app.repository.language import Language
from app.repository.models import RepositoryFile


def test_relationship_models_and_enums() -> None:
    assert RelationshipKind.CALLS.value == "calls"
    assert RelationshipKind.INHERITS.value == "inherits"
    assert RelationshipKind.IMPORTS.value == "imports"

    assert ResolutionStatus.RESOLVED.value == "resolved"
    assert ResolutionStatus.EXTERNAL.value == "external"
    assert ResolutionStatus.UNRESOLVED.value == "unresolved"

    file_id = uuid4()
    raw = RawRelationship(
        source_file_id=file_id,
        target_name="MyClass",
        kind=RelationshipKind.INHERITS,
        source_line=10,
    )
    assert raw.target_name == "MyClass"
    assert raw.kind == RelationshipKind.INHERITS
    assert raw.source_line == 10

    rel = CodeRelationship(
        repository_id=uuid4(),
        file_id=file_id,
        source_line=10,
        target_name="MyClass",
        kind=RelationshipKind.INHERITS,
        status=ResolutionStatus.RESOLVED,
    )
    assert rel.status == ResolutionStatus.RESOLVED


def test_python_relationship_extraction(tmp_path: Path) -> None:
    code = b"""import os
from app.services import MyService

class BaseHandler:
    pass

class CustomHandler(BaseHandler):
    def process(self, data: MyService) -> None:
        os.listdir(".")
        self.helper()

    def helper(self) -> None:
        pass
"""
    file_path = tmp_path / "handler.py"
    file_path.write_bytes(code)

    repo_file = RepositoryFile(
        repository_id=uuid4(),
        path=file_path,
        relative_path=Path("handler.py"),
        extension=".py",
        language=Language.PYTHON,
        size=len(code),
    )
    parser = ParserFactory().get_parser(Language.PYTHON)
    adapter = PythonAdapter()
    extractor = SymbolExtractor(adapter)

    tree_result = parser.parse(repo_file)
    symbols, raw_relationships = extractor.extract_with_relationships(
        tree_result.tree, repo_file, tree_result.source
    )

    assert len(symbols) > 0
    assert len(raw_relationships) > 0

    kinds = {r.kind for r in raw_relationships}
    assert RelationshipKind.IMPORTS in kinds
    assert RelationshipKind.INHERITS in kinds
    assert RelationshipKind.CALLS in kinds
    assert RelationshipKind.USES_TYPE in kinds

    inherits_rel = next(r for r in raw_relationships if r.kind == RelationshipKind.INHERITS)
    assert inherits_rel.target_name == "BaseHandler"

    import_rels = [r for r in raw_relationships if r.kind == RelationshipKind.IMPORTS]
    target_names = {r.target_name for r in import_rels}
    assert "os" in target_names or "MyService" in target_names


def test_symbol_resolver_6_step_cascade() -> None:
    resolver = SymbolResolver()

    repo_id = uuid4()
    file_id = uuid4()

    dummy_file = RepositoryFile(
        id=file_id,
        repository_id=repo_id,
        path=Path("app/main.py"),
        relative_path=Path("app/main.py"),
        extension=".py",
        language=Language.PYTHON,
        size=100,
    )

    class_sym = CodeSymbol(
        id=uuid4(),
        name="BaseService",
        kind=SymbolKind.CLASS,
        language=Language.PYTHON,
        file=dummy_file,
        start_line=1,
        end_line=10,
        start_column=0,
        end_column=20,
        start_byte=0,
        end_byte=100,
        qualified_name="app.services.BaseService",
    )

    symbols_by_id = {class_sym.id: class_sym}
    symbols_by_qualname = {class_sym.qualified_name: class_sym} if class_sym.qualified_name else {}
    symbols_by_name = {"BaseService": [class_sym]}

    raw1 = RawRelationship(
        source_file_id=file_id,
        target_name="BaseService",
        kind=RelationshipKind.INHERITS,
        source_line=5,
        target_module_hint="app.services",
    )

    resolved = resolver.resolve_relationships(
        repository_id=repo_id,
        file_id=file_id,
        raw_relationships=[raw1],
        symbols_by_id=symbols_by_id,
        symbols_by_qualname=symbols_by_qualname,
        symbols_by_name=symbols_by_name,
    )

    assert len(resolved) == 1
    assert resolved[0].status == ResolutionStatus.RESOLVED
    assert resolved[0].target_symbol_id == class_sym.id

    raw2 = RawRelationship(
        source_file_id=file_id,
        target_name="listdir",
        kind=RelationshipKind.CALLS,
        source_line=7,
        target_module_hint="os",
    )
    resolved_ext = resolver.resolve_relationships(
        repository_id=repo_id,
        file_id=file_id,
        raw_relationships=[raw2],
        symbols_by_id=symbols_by_id,
        symbols_by_qualname=symbols_by_qualname,
        symbols_by_name=symbols_by_name,
    )
    assert resolved_ext[0].status == ResolutionStatus.EXTERNAL
    assert resolved_ext[0].target_symbol_id is None
