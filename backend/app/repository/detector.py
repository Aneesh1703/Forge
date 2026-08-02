"""
Create a class variable called EXTENSION_MAP

Dictionary

".py"  -> Language.PYTHON

".ts"  -> Language.TYPESCRIPT

".js"  -> Language.JAVASCRIPT

".go"  -> Language.GO

...

-----------------------------------

Method

detect(path)

Input:
    Path

Algorithm

1. Get file extension.

2. Convert extension to lowercase.

3. Look up extension in EXTENSION_MAP.

4. If found:
       return mapped Language

5. Otherwise:
       return Language.UNKNOWN

"""

from pathlib import Path

from app.repository.language import Language


class LanguageDetector:
    EXTENSION_MAP: dict[str, Language] = {
        ".py": Language.PYTHON,
        ".ts": Language.TYPESCRIPT,
        ".js": Language.JAVASCRIPT,
        ".go": Language.GO,
        ".rs": Language.RUST,
        ".java": Language.JAVA,
        ".cpp": Language.CPP,
        ".c": Language.C,
        ".cs": Language.CSHARP,
        ".kt": Language.KOTLIN,
        ".swift": Language.SWIFT,
        ".php": Language.PHP,
        ".rb": Language.RUBY,
    }

    @staticmethod
    def detect(path: Path) -> Language:
        extension = path.suffix.lower()
        return LanguageDetector.EXTENSION_MAP.get(
            extension,
            Language.UNKNOWN,
        )
