"""
Create IndexerConfig

Fields

batch_size

max_workers

max_file_size

ignored_directories

supported_extensions

------------------------------------------------

Create default instance

config = IndexerConfig()
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndexerConfig:
    batch_size: int = 250
    max_workers: int = 8
    max_file_size_bytes: int = 5 * 1024 * 1024

    ignored_directories: list[str] = field(
        default_factory=lambda: [
            ".venv",
            ".git",
            "__pycache__",
            ".idea",
            ".vscode",
        ]
    )

    supported_extensions: list[str] = field(
        default_factory=lambda: [
            ".py",
            ".js",
            ".ts",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".cs",
            ".go",
            ".php",
            ".rb",
            ".swift",
            ".kt",
            ".rs",
        ]
    )


config = IndexerConfig()
