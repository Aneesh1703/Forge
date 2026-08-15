"""
Issue Understanding Engine

Analyzes issue text to extract structured intents, candidate symbols, target file paths,
relevant test suites, and operational constraints.
"""

import re
from typing import ClassVar

from app.agents.models import (
    CandidateFile,
    CandidateSymbol,
    IssueIntent,
    IssueUnderstanding,
)
from app.parser.models import SymbolKind


class IssueUnderstander:
    """
    Parser engine transforming raw software engineering issue descriptions into
    structured IssueUnderstanding DTOs.
    """

    FILE_PATH_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b[\w\-\.\/\\]+\.(?:py|js|ts|jsx|tsx|json|yml|yaml|md|toml|sql)\b",
        re.IGNORECASE,
    )
    BACKTICK_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"`([^`]+)`")
    SYMBOL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"\b[A-Za-z_][A-Za-z0-9_\.]*\b")

    STOP_WORDS: ClassVar[set[str]] = {
        "the",
        "and",
        "for",
        "with",
        "where",
        "when",
        "what",
        "how",
        "this",
        "that",
        "from",
        "should",
        "must",
        "cannot",
        "does",
        "not",
        "working",
        "issue",
        "error",
        "bug",
        "fix",
        "add",
        "support",
        "python",
        "test",
        "tests",
    }

    def analyze_issue(self, title: str, description: str = "") -> IssueUnderstanding:
        """
        Parses raw title & description to produce structured IssueUnderstanding.
        """
        combined = f"{title}\n{description}".strip()
        lower = combined.lower()

        # 1. Intent Classification
        intent = self._classify_intent(lower)

        # 2. Extract Candidate Files
        files = self._extract_candidate_files(combined)

        # 3. Extract Candidate Symbols
        symbols = self._extract_candidate_symbols(combined)

        # 4. Extract Test Targets
        tests = self._extract_test_targets(combined, files)

        # 5. Extract Constraints
        constraints = self._extract_constraints(combined)

        return IssueUnderstanding.create(
            title=title,
            description=description,
            intent=intent,
            symbols=symbols,
            files=files,
            tests=tests,
            constraints=constraints,
        )

    def _classify_intent(self, text_lower: str) -> IssueIntent:
        if any(
            k in text_lower
            for k in [
                "bug",
                "fix",
                "issue",
                "error",
                "exception",
                "fail",
                "crash",
                "traceback",
                "broken",
            ]
        ):
            return IssueIntent.BUG_FIX
        if any(
            k in text_lower
            for k in [
                "add",
                "support",
                "feature",
                "new",
                "implement",
                "enable",
                "allow",
            ]
        ):
            return IssueIntent.FEATURE_REQUEST
        if any(k in text_lower for k in ["refactor", "clean", "simplify", "restructure", "rename"]):
            return IssueIntent.REFACTORING
        if any(
            k in text_lower
            for k in ["perf", "speed", "fast", "slow", "memory", "latency", "optimize"]
        ):
            return IssueIntent.PERFORMANCE
        if any(k in text_lower for k in ["doc", "readme", "typo", "comment"]):
            return IssueIntent.DOCUMENTATION
        return IssueIntent.UNKNOWN

    def _extract_candidate_files(self, text: str) -> list[CandidateFile]:
        matches = self.FILE_PATH_PATTERN.findall(text)
        seen: set[str] = set()
        candidates: list[CandidateFile] = []

        for m in matches:
            clean = m.strip().replace("\\", "/")
            if clean not in seen and not clean.startswith("http"):
                seen.add(clean)
                confidence = 0.9 if ("/" in clean or "test_" in clean) else 0.7
                candidates.append(CandidateFile(file_path=clean, confidence=confidence))

        return candidates

    def _extract_candidate_symbols(self, text: str) -> list[CandidateSymbol]:
        seen: set[str] = set()
        candidates: list[CandidateSymbol] = []

        # High-confidence backtick tokens (e.g. `APIRouter` or `HTTPClient.request()`)
        backticks = self.BACKTICK_PATTERN.findall(text)
        for b in backticks:
            token = b.strip()
            if token.endswith("()"):
                token = token[:-2].strip()
            if self.SYMBOL_PATTERN.fullmatch(token) and token.lower() not in self.STOP_WORDS:
                seen.add(token)
                kind_hint = SymbolKind.CLASS if token[0].isupper() else SymbolKind.FUNCTION
                candidates.append(
                    CandidateSymbol(
                        name=token,
                        confidence=0.95,
                        kind_hint=kind_hint,
                    )
                )

        # Standard token extraction
        tokens = self.SYMBOL_PATTERN.findall(text)
        for t in tokens:
            if t in seen or t.lower() in self.STOP_WORDS or len(t) < 3:
                continue

            is_camel_pascal = bool(re.search(r"[A-Z]", t))
            is_snake_or_dotted = "_" in t or "." in t

            if is_camel_pascal or is_snake_or_dotted:
                seen.add(t)
                kind_hint = SymbolKind.CLASS if t[0].isupper() else SymbolKind.FUNCTION
                candidates.append(
                    CandidateSymbol(
                        name=t,
                        confidence=0.75,
                        kind_hint=kind_hint,
                    )
                )

        return candidates

    def _extract_test_targets(self, text: str, files: list[CandidateFile]) -> list[str]:
        test_files: set[str] = set()

        for f in files:
            if "test" in f.file_path.lower():
                test_files.add(f.file_path)

        # Regex search for test mentions (e.g. tests/test_auth.py)
        test_matches = re.findall(
            r"\b(?:tests?\/[\w\-\/]+\.py|test_[\w\-]+\.py)\b", text, re.IGNORECASE
        )
        for tm in test_matches:
            test_files.add(tm.strip())

        return sorted(list(test_files))

    def _extract_constraints(self, text: str) -> list[str]:
        constraints: list[str] = []
        text_lower = text.lower()

        patterns = [
            (
                "no breaking change",
                "Must preserve backward compatibility without breaking changes.",
            ),
            ("thread safe", "Must be thread-safe."),
            ("async", "Must support asynchronous async/await execution."),
            ("performance", "Must maintain low latency execution bounds."),
        ]

        for trigger, msg in patterns:
            if trigger in text_lower:
                constraints.append(msg)

        return constraints
