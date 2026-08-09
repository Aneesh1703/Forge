from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.repository.language import Language


@dataclass
class Repository:
    name: str
    root_path: Path

    id: UUID = field(default_factory=uuid4)

    git_url: str | None = None
    default_branch: str | None = None
    indexed_at: datetime | None = None


@dataclass
class RepositoryFile:
    repository_id: UUID

    path: Path
    relative_path: Path

    extension: str
    language: Language

    size: int

    id: UUID = field(default_factory=uuid4)
    content_hash: str = ""
    last_modified: datetime | None = None
