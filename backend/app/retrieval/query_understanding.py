"""
Stage 1: Query Understanding Engine

Parses user queries to detect structural intent, extract identifier tokens, and infer
optimal metadata filters (SymbolKind, Language, Chunk Levels) for semantic search.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from app.parser.models import SymbolKind
from app.repository.language import Language


class QueryIntent(str, Enum):
    """Classified intent of a developer code search query."""

    SYMBOL_LOOKUP = "symbol_lookup"
    CALL_GRAPH = "call_graph"
    ARCHITECTURE_OVERVIEW = "architecture_overview"
    DEPENDENCY = "dependency"
    GENERAL = "general"


@dataclass(frozen=True)
class ParsedQuery:
    """
    Structured query understanding DTO.
    """

    raw_query: str
    intent: QueryIntent
    target_identifiers: list[str] = field(default_factory=list)
    symbol_kinds: set[SymbolKind] = field(default_factory=set)
    suggested_levels: list[int] = field(default_factory=list)
    language_hint: Language | None = None


class QueryUnderstandingEngine:
    """
    Engine analyzing natural language & code queries to optimize retrieval filters.
    """

    def analyze_query(self, query_text: str) -> ParsedQuery:
        """
        Parses query intent, extracts symbol identifiers, and infers filter bounds.
        """
        raw = query_text.strip()
        if not raw:
            return ParsedQuery(raw_query="", intent=QueryIntent.GENERAL)

        # 1. Extract potential symbol identifiers
        # (camelCase, PascalCase, snake_case, dotted names, capitalized words)
        id_pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_\.]*\b")
        words = id_pattern.findall(raw)

        stop_words = {
            "where",
            "is",
            "are",
            "how",
            "which",
            "what",
            "the",
            "handled",
            "configured",
            "modified",
            "python",
            "in",
            "calls",
            "functions",
            "should",
            "i",
        }

        code_identifiers: list[str] = []
        for w in words:
            if w.lower() in stop_words:
                continue
            is_camel_pascal = bool(re.search(r"[A-Z]", w))
            is_snake_or_dotted = "_" in w or "." in w
            if is_camel_pascal or is_snake_or_dotted or len(w) > 2:
                code_identifiers.append(w)

        # 2. Detect Intent & SymbolKind hints
        lower = raw.lower()

        intent = QueryIntent.GENERAL
        symbol_kinds: set[SymbolKind] = set()
        suggested_levels: list[int] = []

        if any(k in lower for k in ["call", "caller", "callee", "who calls", "called by"]):
            intent = QueryIntent.CALL_GRAPH
            suggested_levels = [1, 2]
        elif any(
            k in lower
            for k in [
                "where is",
                "find class",
                "find function",
                "definition",
                "implementation of",
            ]
        ) or bool(code_identifiers):
            intent = QueryIntent.SYMBOL_LOOKUP
            suggested_levels = [1, 2, 3]
        elif any(k in lower for k in ["overview", "architecture", "structure", "module", "how is"]):
            intent = QueryIntent.ARCHITECTURE_OVERVIEW
            suggested_levels = [4, 5]
        elif any(k in lower for k in ["import", "depend", "package", "require"]):
            intent = QueryIntent.DEPENDENCY
            suggested_levels = [4, 5]

        # Infer SymbolKind filters
        if "class" in lower:
            symbol_kinds.add(SymbolKind.CLASS)
        if any(k in lower for k in ["function", "def", "method"]):
            symbol_kinds.add(SymbolKind.FUNCTION)
            symbol_kinds.add(SymbolKind.METHOD)
        if "interface" in lower:
            symbol_kinds.add(SymbolKind.INTERFACE)

        # Default levels if none inferred
        if not suggested_levels:
            suggested_levels = [1, 2, 3, 4, 5]

        # Language hint detection
        lang_hint: Language | None = None
        if "python" in lower or ".py" in lower:
            lang_hint = Language.PYTHON
        elif "typescript" in lower or "ts" in lower:
            lang_hint = Language.TYPESCRIPT
        elif "javascript" in lower or "js" in lower:
            lang_hint = Language.JAVASCRIPT

        return ParsedQuery(
            raw_query=raw,
            intent=intent,
            target_identifiers=code_identifiers,
            symbol_kinds=symbol_kinds,
            suggested_levels=suggested_levels,
            language_hint=lang_hint,
        )
