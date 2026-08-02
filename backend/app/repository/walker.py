"""
Create RepositoryWalker

Method:
    walk(repository)

Input:
    Path

Algorithm

1. Verify the path exists.
2. Verify it is a directory.
3. Create an empty collection.
4. Iterate over repo.rglob("*").
5. If the current path is a file:
       add it to the collection.
6. Return the collection.
"""

from pathlib import Path
from typing import Any

from pathspec import PathSpec

from app.repository.detector import LanguageDetector
from app.repository.models import RepositoryFile


class RepositoryWalker:
    IGNORED_DIRS = {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
    }

    def walk(self, repository: Path) -> list[RepositoryFile]:
        if not repository.exists():
            raise FileNotFoundError(f"{repository} does not exist.")

        if not repository.is_dir():
            raise NotADirectoryError(f"{repository} is not a directory.")

        spec = self._load_gitignore(repository)

        collection: list[RepositoryFile] = []
        for path in repository.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.IGNORED_DIRS for part in path.parts):
                continue
            rel_path = path.relative_to(repository)
            if spec.match_file(str(rel_path)):
                continue

            collection.append(
                RepositoryFile(
                    path=path,
                    relative_path=rel_path,
                    extension=path.suffix,
                    language=LanguageDetector.detect(path),
                    size=path.stat().st_size,
                )
            )

        return collection

    def _load_gitignore(self, repository: Path) -> PathSpec[Any]:
        gitignore_path = repository / ".gitignore"

        if not gitignore_path.exists():
            return PathSpec.from_lines("gitwildmatch", [])

        patterns = gitignore_path.read_text(encoding="utf-8").splitlines()

        return PathSpec.from_lines("gitwildmatch", patterns)
