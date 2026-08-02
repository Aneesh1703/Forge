from dataclasses import dataclass
from pathlib import Path

from app.repository.language import Language

"""
Create RepositoryFile

Fields

- path
- relative_path
- extension
- language
- size
"""


@dataclass
class RepositoryFile:
    path: Path
    relative_path: Path
    extension: str
    language: Language
    size: int
