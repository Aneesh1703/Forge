"""
Phase 9A: Coding Agent Domain Models & Execution Policy Dataclasses
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class ExecutionPolicy(str, Enum):
    """Human-in-the-Loop approval execution policy."""

    MANUAL = "MANUAL"
    SEMI_AUTONOMOUS = "SEMI_AUTONOMOUS"
    AUTONOMOUS = "AUTONOMOUS"


class ModelTier(str, Enum):
    """Escalation model tiers for code reasoning."""

    LEVEL_0_DETERMINISTIC = "LEVEL_0_DETERMINISTIC"
    LEVEL_1_FAST = "LEVEL_1_FAST"
    LEVEL_2_STRONG = "LEVEL_2_STRONG"
    LEVEL_3_FLAGSHIP = "LEVEL_3_FLAGSHIP"


@dataclass(frozen=True)
class ComplexityScore:
    """Calculated complexity score & token budget assignment."""

    score: int  # 0 to 100
    tier: ModelTier
    token_budget: int
    reasoning_summary: str = ""


@dataclass
class SymbolTarget:
    """Target symbol specification for patch application."""

    file_path: str
    qualified_symbol_name: str
    expected_content_hash: str
    replacement_code: str

    @classmethod
    def compute_hash(cls, source_code: str) -> str:
        """Computes SHA-256 content hash of target symbol source range."""
        return hashlib.sha256(source_code.strip().encode("utf-8")).hexdigest()


@dataclass
class CodeHunk:
    """Targeted replacement hunk within a source file."""

    target_symbol: SymbolTarget
    start_byte: int | None = None
    end_byte: int | None = None
    start_line: int | None = None
    end_line: int | None = None


@dataclass
class CodePatch:
    """Structured code patch produced by CodingAgent."""

    files_changed: list[str] = field(default_factory=list)
    hunks: list[CodeHunk] = field(default_factory=list)
    explanation: str = ""
    confidence: float = 1.0
