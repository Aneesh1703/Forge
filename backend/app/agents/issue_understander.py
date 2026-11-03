"""
Issue Understanding Engine

Analyzes issue text to extract structured intents, candidate symbols, target file paths,
relevant test suites, and operational constraints. `ground()` then checks every mentioned
path against the real repository listing: a path that does not exist is recorded as
unresolved, never guessed.
"""

import re
from dataclasses import replace
from uuid import UUID

from app.agents.models import (
    CandidateFile,
    CandidateSymbol,
    IssueIntent,
    IssueUnderstanding,
)
from app.parser.models import SymbolKind
from app.repository.listing import is_test_path

FILE_EXTENSIONS = "py|js|ts|jsx|tsx|json|yml|yaml|md|toml|sql|go|rs|java|rb|sh|cfg|ini|txt"
# Removed before path extraction so "https://x.com/a.py" never yields "x.com/a.py".
URL_PATTERN = re.compile(r"(?:\b(?:https?|ftp)://|\bwww\.)\S+", re.IGNORECASE)
FILE_PATH_PATTERN = re.compile(
    rf"(?<![\w\-./\\])[\w\-./\\]+\.(?:{FILE_EXTENSIONS})(?![\w\-])", re.IGNORECASE
)
KNOWN_EXTENSION_PATTERN = re.compile(rf"\.(?:{FILE_EXTENSIONS})$", re.IGNORECASE)
BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
# Identifiers and dotted names, never starting in the middle of another token.
SYMBOL_PATTERN = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# What may precede a sentence's first word on its line: a list or heading marker, then
# opening brackets or quotes ("- Update", "## See", "(See below)").
LINE_START_PREFIX = re.compile(r"\s*(?:[-*+]|#+|\d+[.)])?\s*[(\"'\[]*")

STOP_WORDS = frozenset(
    {
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
)
NOISE_SYMBOLS = frozenset({"e.g", "i.e", "etc"})

# Checked in this order; the first intent with a whole-word hit wins. Generic feature words
# ("add", "new") come after removal and docs words so "Remove the feature flag" is a
# refactor and "Add docstrings" is documentation.
INTENT_KEYWORDS: tuple[tuple[IssueIntent, frozenset[str]], ...] = (
    (
        IssueIntent.BUG_FIX,
        frozenset(
            {
                "bug",
                "bugs",
                "fix",
                "fixes",
                "error",
                "errors",
                "exception",
                "exceptions",
                "fail",
                "fails",
                "failed",
                "failing",
                "failure",
                "crash",
                "crashes",
                "crashed",
                "traceback",
                "broken",
                "regression",
            }
        ),
    ),
    (
        IssueIntent.REFACTORING,
        frozenset(
            {
                "refactor",
                "clean",
                "cleanup",
                "simplify",
                "restructure",
                "rename",
                "remove",
                "delete",
                "drop",
                "deprecate",
            }
        ),
    ),
    (
        IssueIntent.DOCUMENTATION,
        frozenset(
            {
                "doc",
                "docs",
                "documentation",
                "docstring",
                "docstrings",
                "readme",
                "typo",
                "typos",
            }
        ),
    ),
    (
        IssueIntent.FEATURE_REQUEST,
        frozenset({"add", "adds", "support", "feature", "new", "implement", "enable", "allow"}),
    ),
    (
        IssueIntent.PERFORMANCE,
        frozenset(
            {
                "perf",
                "performance",
                "speed",
                "fast",
                "faster",
                "slow",
                "slower",
                "memory",
                "latency",
                "optimize",
                "optimise",
            }
        ),
    ),
)
REMOVAL_WORDS = frozenset({"remove", "delete", "drop", "deprecate"})
CONSTRAINT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bno breaking changes?\b"),
        "Must preserve backward compatibility without breaking changes.",
    ),
    (re.compile(r"\bthread[\s-]safe\b"), "Must be thread-safe."),
    (re.compile(r"\basync\b"), "Must support asynchronous async/await execution."),
    (re.compile(r"\bperformance\b"), "Must maintain low latency execution bounds."),
)


class IssueUnderstander:
    """
    Parser engine transforming raw software engineering issue descriptions into
    structured IssueUnderstanding DTOs.
    """

    def analyze_issue(
        self, title: str, description: str = "", *, issue_id: UUID | None = None
    ) -> IssueUnderstanding:
        """Parses raw title & description into an (ungrounded) IssueUnderstanding."""
        text = strip_urls(f"{title}\n{description}".strip())
        words = _words(text)
        files = _extract_candidate_files(text)
        return IssueUnderstanding.create(
            title=title,
            description=description,
            intent=_classify_intent(words),
            symbols=_extract_candidate_symbols(text),
            files=files,
            tests=[f.file_path for f in files if is_test_path(f.file_path)],
            constraints=_extract_constraints(text.lower()),
            issue_id=issue_id,
            requested_actions=["delete"] if words & REMOVAL_WORDS else [],
        )


def split_issue_prompt(prompt: str) -> tuple[str, str]:
    """The pipeline stores one prompt string: its first non-empty line is the title."""
    lines = prompt.strip().splitlines()
    if not lines:
        return "", ""
    return lines[0].strip(), "\n".join(lines[1:]).strip()


def ground(understanding: IssueUnderstanding, repo_files: frozenset[str]) -> IssueUnderstanding:
    """Resolve mentioned paths against the repository; unknown paths become unresolved."""
    unresolved = list(understanding.unresolved_paths)
    files: list[CandidateFile] = []
    for candidate in understanding.affected_files:
        resolved = resolve_path(candidate.file_path, repo_files)
        if resolved is None:
            _append_unique(unresolved, candidate.file_path)
        elif resolved not in {f.file_path for f in files}:
            files.append(replace(candidate, file_path=resolved))

    tests: list[str] = []
    for mention in understanding.relevant_tests:
        resolved = resolve_path(mention, repo_files)
        if resolved is None:
            _append_unique(unresolved, mention)
        elif is_test_path(resolved):
            _append_unique(tests, resolved)

    return replace(
        understanding, affected_files=files, relevant_tests=tests, unresolved_paths=unresolved
    )


def resolve_path(mention: str, repo_files: frozenset[str]) -> str | None:
    """Exact match, else the single repo file ending in "/<mention>"; ambiguity is None."""
    path = normalise_path(mention)
    if path in repo_files:
        return path
    matches = [f for f in repo_files if f.endswith("/" + path)]
    return matches[0] if len(matches) == 1 else None


def normalise_path(path: str) -> str:
    """Issue text uses Windows separators and "./" prefixes; the listing uses neither."""
    clean = path.strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean


def strip_urls(text: str) -> str:
    return URL_PATTERN.sub(" ", text)


def _words(text: str) -> frozenset[str]:
    """Whole words, so "prefix" never counts as "fix" nor "asyncio" as "async"."""
    return frozenset(re.findall(r"\w+", text.lower()))


def _classify_intent(words: frozenset[str]) -> IssueIntent:
    for intent, keywords in INTENT_KEYWORDS:
        if words & keywords:
            return intent
    return IssueIntent.UNKNOWN


def _extract_candidate_files(text: str) -> list[CandidateFile]:
    seen: set[str] = set()
    candidates: list[CandidateFile] = []
    for match in FILE_PATH_PATTERN.findall(text):
        clean = normalise_path(match)
        if clean and clean not in seen:
            seen.add(clean)
            confidence = 0.9 if ("/" in clean or "test_" in clean) else 0.7
            candidates.append(CandidateFile(file_path=clean, confidence=confidence))
    return candidates


def _extract_candidate_symbols(text: str) -> list[CandidateSymbol]:
    """Backticked tokens first (strongest), then call-like, dotted and code-shaped words."""
    by_token: dict[str, CandidateSymbol] = {}

    for raw in BACKTICK_PATTERN.findall(text):
        token = raw.strip().removesuffix("()").strip()
        if SYMBOL_PATTERN.fullmatch(token) and not _is_noise(token):
            by_token.setdefault(token, _make_symbol(token, 0.95))

    # Paths and e-mail addresses would otherwise yield their segments ("my_module") or
    # hosts ("example.com") as symbols.
    prose = EMAIL_PATTERN.sub(" ", FILE_PATH_PATTERN.sub(" ", text))
    for match in SYMBOL_PATTERN.finditer(prose):
        token = match.group()
        if token in by_token or _is_noise(token):
            continue
        if prose.startswith("(", match.end()):
            confidence = 0.9
        elif token.lower() in STOP_WORDS:
            continue  # Plain English words count only when written as a call.
        elif "." in token:
            confidence = 0.85
        elif _looks_like_code(token, at_sentence_start=_at_sentence_start(prose, match.start())):
            confidence = 0.75
        else:
            continue
        by_token[token] = _make_symbol(token, confidence)

    return list(by_token.values())


def _is_noise(token: str) -> bool:
    """File names and abbreviations are never symbols, even when backticked."""
    return token.lower() in NOISE_SYMBOLS or bool(KNOWN_EXTENSION_PATTERN.search(token))


def _looks_like_code(token: str, *, at_sentence_start: bool) -> bool:
    if len(token) < 3 or (token.isupper() and "_" not in token):
        return False
    if "_" in token.strip("_"):
        return True
    if any(c.isupper() for c in token[1:]):
        return True  # CamelCase / mixedCase
    # A plain "Capitalised" word is a class only mid-sentence ("See", "Update" are not).
    return token[0].isupper() and not at_sentence_start


def _at_sentence_start(text: str, index: int) -> bool:
    """First word of its line (after list/heading markers and brackets) or after .!?:"""
    before = text[:index]
    line = before[before.rfind("\n") + 1 :]
    if LINE_START_PREFIX.fullmatch(line):
        return True
    stripped = before.rstrip().rstrip("(\"'[").rstrip()
    return not stripped or stripped[-1] in ".!?:"


def _make_symbol(token: str, confidence: float) -> CandidateSymbol:
    """Dotted names keep the full path as a hint and are named by their last segment."""
    segments = token.split(".")
    name = segments[-1]
    if len(segments) > 1:
        is_method = name[:1].islower() and segments[-2][:1].isupper()
        kind = SymbolKind.METHOD if is_method else _kind_for_name(name)
        return CandidateSymbol(
            name=name, qualified_name_hint=token, kind_hint=kind, confidence=confidence
        )
    return CandidateSymbol(name=name, kind_hint=_kind_for_name(name), confidence=confidence)


def _kind_for_name(name: str) -> SymbolKind:
    """CONSTANT_CASE, CapWords class, anything else a function."""
    if name.isupper():
        return SymbolKind.CONSTANT
    return SymbolKind.CLASS if name[0].isupper() else SymbolKind.FUNCTION


def _extract_constraints(text_lower: str) -> list[str]:
    return [message for pattern, message in CONSTRAINT_PATTERNS if pattern.search(text_lower)]


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)
