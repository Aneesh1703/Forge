from pathlib import Path
from uuid import uuid4

from app.parser.adapters.python import PythonAdapter
from app.parser.extractor import SymbolExtractor
from app.parser.models import CodeSymbol, SymbolKind
from app.parser.modifiers import Modifier
from app.parser.parser_factory import ParserFactory
from app.parser.types import ParameterKind
from app.parser.visibility import Visibility
from app.repository.detector import LanguageDetector
from app.repository.models import RepositoryFile


def _parse_and_extract(source: str, tmp_path: Path) -> list[CodeSymbol]:
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(source, encoding="utf-8")

    detector = LanguageDetector()
    repo_file = RepositoryFile(
        repository_id=uuid4(),
        path=file_path,
        relative_path=Path("test_sample.py"),
        extension=".py",
        language=detector.detect(file_path),
        size=file_path.stat().st_size,
    )

    parser = ParserFactory().get_parser(repo_file.language)
    parse_result = parser.parse(repo_file)

    extractor = SymbolExtractor(PythonAdapter())
    symbols = extractor.extract(
        tree=parse_result.tree,
        repository_file=repo_file,
        source=parse_result.source,
    )
    return symbols


def test_python_symbol_extraction(tmp_path: Path) -> None:
    """
    End-to-end test for basic symbol hierarchy extraction.
    """
    source = """
class User:
    def login(self):
        pass

def hello():
    pass
"""
    symbols = _parse_and_extract(source, tmp_path)

    assert len(symbols) == 3
    assert symbols[0].name == "User"
    assert symbols[0].kind == SymbolKind.CLASS

    assert symbols[1].name == "login"
    assert symbols[1].kind == SymbolKind.METHOD
    assert symbols[1].parent is not None and symbols[1].parent.name == "User"

    assert symbols[2].name == "hello"
    assert symbols[2].kind == SymbolKind.FUNCTION


def test_python_parameter_extraction(tmp_path: Path) -> None:
    """
    Test detailed parameter extraction including typed, default, splat,
    positional-only (/), and keyword-only (*) parameters.
    """
    source = """
def complex_func(a, /, b: int, c=10, d: str = "hello", *args, e: float = 3.14, *, f, **kwargs):
    pass
"""
    symbols = _parse_and_extract(source, tmp_path)
    assert len(symbols) == 1

    fn = symbols[0]
    params = fn.parameters
    assert len(params) == 8

    # a -> POSITIONAL_ONLY
    assert params[0].name == "a"
    assert params[0].kind == ParameterKind.POSITIONAL_ONLY

    # b: int -> POSITIONAL_OR_KEYWORD
    assert params[1].name == "b"
    assert params[1].kind == ParameterKind.POSITIONAL_OR_KEYWORD
    assert params[1].type_annotation == "int"
    assert params[1].default_value is None

    # c=10 -> POSITIONAL_OR_KEYWORD
    assert params[2].name == "c"
    assert params[2].kind == ParameterKind.POSITIONAL_OR_KEYWORD
    assert params[2].type_annotation is None
    assert params[2].default_value == "10"

    # d: str = "hello" -> POSITIONAL_OR_KEYWORD
    assert params[3].name == "d"
    assert params[3].kind == ParameterKind.POSITIONAL_OR_KEYWORD
    assert params[3].type_annotation == "str"
    assert params[3].default_value == '"hello"'

    # *args -> VAR_POSITIONAL
    assert params[4].name == "args"
    assert params[4].kind == ParameterKind.VAR_POSITIONAL

    # e: float = 3.14 -> KEYWORD_ONLY (following *args)
    assert params[5].name == "e"
    assert params[5].kind == ParameterKind.KEYWORD_ONLY
    assert params[5].type_annotation == "float"
    assert params[5].default_value == "3.14"

    # f -> KEYWORD_ONLY (following *)
    assert params[6].name == "f"
    assert params[6].kind == ParameterKind.KEYWORD_ONLY

    # **kwargs -> VAR_KEYWORD
    assert params[7].name == "kwargs"
    assert params[7].kind == ParameterKind.VAR_KEYWORD


def test_python_return_type_and_documentation(tmp_path: Path) -> None:
    """
    Test extraction of return types and docstrings for functions and classes.
    """
    source = '''
class Service:
    """Main service component."""

    def process(self, item: str) -> list[str]:
        """Processes the item and returns a list."""
        return [item]
'''
    symbols = _parse_and_extract(source, tmp_path)
    assert len(symbols) == 2

    cls = symbols[0]
    assert cls.name == "Service"
    assert cls.documentation == "Main service component."

    method = symbols[1]
    assert method.name == "process"
    assert method.return_type == "list[str]"
    assert method.documentation == "Processes the item and returns a list."


def test_python_decorators_and_modifiers(tmp_path: Path) -> None:
    """
    Test extraction of decorators as attributes and conversion to universal Modifiers.
    """
    source = """
class Worker:
    @staticmethod
    def create():
        pass

    @property
    def name(self):
        pass

    @abstractmethod
    def run(self):
        pass

    async def fetch(self):
        yield 42
"""
    symbols = _parse_and_extract(source, tmp_path)
    # symbols[0] = Worker, [1] = create, [2] = name, [3] = run, [4] = fetch
    symbols_by_name = {s.name: s for s in symbols}

    create_fn = symbols_by_name["create"]
    assert Modifier.STATIC in create_fn.modifiers
    assert any(attr.name == "staticmethod" for attr in create_fn.attributes)

    prop_fn = symbols_by_name["name"]
    assert Modifier.PROPERTY in prop_fn.modifiers

    run_fn = symbols_by_name["run"]
    assert Modifier.ABSTRACT in run_fn.modifiers

    fetch_fn = symbols_by_name["fetch"]
    assert Modifier.ASYNC in fetch_fn.modifiers
    assert Modifier.GENERATOR in fetch_fn.modifiers


def test_python_visibility_conventions(tmp_path: Path) -> None:
    """
    Test visibility detection based on Python naming conventions.
    """
    source = """
class Secret:
    def public_method(self):
        pass

    def _protected_method(self):
        pass

    def __private_method(self):
        pass

    def __init__(self):
        pass
"""
    symbols = _parse_and_extract(source, tmp_path)
    symbols_by_name = {s.name: s for s in symbols}

    assert symbols_by_name["public_method"].visibility == Visibility.PUBLIC
    assert symbols_by_name["_protected_method"].visibility == Visibility.PROTECTED
    assert symbols_by_name["__private_method"].visibility == Visibility.PRIVATE
    assert symbols_by_name["__init__"].visibility == Visibility.PUBLIC


def test_python_base_classes(tmp_path: Path) -> None:
    """
    Test superclasses extraction for class definitions.
    """
    source = """
class AdminUser(User, Serializable, Protocol[T]):
    pass
"""
    symbols = _parse_and_extract(source, tmp_path)
    assert len(symbols) == 1
    admin_cls = symbols[0]

    assert admin_cls.name == "AdminUser"
    assert admin_cls.base_classes == ["User", "Serializable", "Protocol[T]"]
