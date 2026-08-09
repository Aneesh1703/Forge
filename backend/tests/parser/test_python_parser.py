from pathlib import Path
from uuid import uuid4

from app.parser.adapters.python import PythonAdapter
from app.parser.extractor import SymbolExtractor
from app.parser.models import SymbolKind
from app.parser.parser_factory import ParserFactory
from app.repository.detector import LanguageDetector
from app.repository.models import RepositoryFile


def test_python_symbol_extraction(tmp_path: Path) -> None:
    """
    End-to-end test for parsing a Python source file and extracting symbols.
    """

    source = """
class User:
    def login(self):
        pass

def hello():
    pass
"""

    file_path = tmp_path / "sample.py"
    file_path.write_text(source, encoding="utf-8")

    language_detector = LanguageDetector()

    repository_file = RepositoryFile(
        repository_id=uuid4(),
        path=file_path,
        relative_path=Path("sample.py"),
        extension=".py",
        language=language_detector.detect(file_path),
        size=file_path.stat().st_size,
    )

    parser = ParserFactory().get_parser(repository_file.language)
    result = parser.parse(repository_file)

    extractor = SymbolExtractor(PythonAdapter())

    symbols = extractor.extract(
        tree=result.tree,
        repository_file=repository_file,
        source=result.source,
    )

    print("\nExtracted Symbols:")

    for symbol in symbols:
        print(
            f"""
    Name        : {symbol.name}
    Kind        : {symbol.kind.value}
    Language    : {symbol.language.value}
    Parent      : {symbol.parent.name if symbol.parent else None}
    Lines       : {symbol.start_line}-{symbol.end_line}
    Columns     : {symbol.start_column}-{symbol.end_column}
    """
        )

    assert len(symbols) == 3

    assert symbols[0].name == "User"
    assert symbols[0].kind == SymbolKind.CLASS

    assert symbols[1].name == "login"
    assert symbols[1].kind == SymbolKind.METHOD

    assert symbols[2].name == "hello"
    assert symbols[2].kind == SymbolKind.FUNCTION
