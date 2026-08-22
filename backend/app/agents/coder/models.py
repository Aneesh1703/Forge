"""
Phase 9A: Coding Agent Domain Models & Execution Policy Dataclasses
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionPolicy(str, Enum):
    """Human-in-the-Loop approval execution policy."""

    MANUAL = "MANUAL"
    SEMI_AUTONOMOUS = "SEMI_AUTONOMOUS"
    AUTONOMOUS = "AUTONOMOUS"


class SymbolAction(str, Enum):
    """Explicit symbol operation type for surgical patching."""

    MODIFY = "MODIFY"
    ADD = "ADD"
    DELETE = "DELETE"
    REPLACE_FILE = "REPLACE_FILE"


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
    """Target symbol specification for surgical patch application."""

    file_path: str
    qualified_symbol_name: str
    expected_content_hash: str
    replacement_code: str
    original_snippet: str = ""
    anchor_symbol: str = ""
    anchor_position: str = "after"  # "after", "before", "replace"

    @classmethod
    def compute_hash(cls, source_code: str) -> str:
        """Computes SHA-256 content hash of target symbol source range."""
        return hashlib.sha256(source_code.strip().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "qualified_symbol_name": self.qualified_symbol_name,
            "expected_content_hash": self.expected_content_hash,
            "replacement_code": self.replacement_code,
            "original_snippet": self.original_snippet,
            "anchor_symbol": self.anchor_symbol,
            "anchor_position": self.anchor_position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymbolTarget":
        return cls(
            file_path=data.get("file_path", ""),
            qualified_symbol_name=data.get("qualified_symbol_name", ""),
            expected_content_hash=data.get("expected_content_hash", ""),
            replacement_code=data.get("replacement_code", ""),
            original_snippet=data.get("original_snippet", ""),
            anchor_symbol=data.get("anchor_symbol", ""),
            anchor_position=data.get("anchor_position", "after"),
        )


@dataclass
class CodeHunk:
    """Targeted replacement hunk within a source file."""

    target_symbol: SymbolTarget
    action: SymbolAction = SymbolAction.MODIFY
    start_byte: int | None = None
    end_byte: int | None = None
    start_line: int | None = None
    end_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        action_val = (
            self.action.value if isinstance(self.action, SymbolAction) else str(self.action)
        )
        return {
            "target_symbol": self.target_symbol.to_dict(),
            "action": action_val,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeHunk":
        ts_data = data.get("target_symbol", {})
        ts = SymbolTarget.from_dict(ts_data) if isinstance(ts_data, dict) else ts_data
        raw_act = data.get("action", SymbolAction.MODIFY)
        try:
            act = SymbolAction(raw_act)
        except ValueError:
            act = SymbolAction.MODIFY

        return cls(
            target_symbol=ts,
            action=act,
            start_byte=data.get("start_byte"),
            end_byte=data.get("end_byte"),
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
        )


@dataclass
class CodePatch:
    """Structured multi-file code patch produced by CodingAgent."""

    files_changed: list[str] = field(default_factory=list)
    hunks: list[CodeHunk] = field(default_factory=list)
    explanation: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_changed": self.files_changed,
            "hunks": [h.to_dict() for h in self.hunks],
            "explanation": self.explanation,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodePatch":
        raw_hunks = data.get("hunks", [])
        hunks = [CodeHunk.from_dict(h) if isinstance(h, dict) else h for h in raw_hunks]
        return cls(
            files_changed=data.get("files_changed", []),
            hunks=hunks,
            explanation=data.get("explanation", ""),
            confidence=data.get("confidence", 1.0),
        )
