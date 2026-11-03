"""
Evidence Investigator

Builds one hypothesis per issue symbol (plus DELETE hypotheses on request) and attaches only
evidence that names that hypothesis exactly: issue mentions, grounded file matches, mapped
tests and Repository Brain recall. Paths are never guessed: a hypothesis targets a file only
when that file is in the repository listing.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from app.agents.evidence.confidence import ConfidenceGate
from app.agents.evidence.models import Evidence, EvidenceGraph, EvidenceSource, Hypothesis
from app.agents.models import CandidateSymbol, IssueUnderstanding
from app.brain.memory import RepositoryBrain, RepositoryMemory
from app.repository.listing import is_test_path

MENTION_RELEVANCE = 0.80
ISSUE_FILE_RELEVANCE = 0.90
RESOLVER_FILE_CONFIDENCE = 0.70
RESOLVER_FILE_RELEVANCE = 0.80
TEST_CONFIDENCE = 0.85
TEST_RELEVANCE = 0.90
BRAIN_CONFIDENCE = 0.90
BRAIN_RELEVANCE = 0.85
BRAIN_RECALL_THRESHOLD = 0.60


def mentions_identifier(text: str, identifier: str) -> bool:
    """True when `identifier` occurs in `text` on identifier boundaries (`get` ≠ `get_user`)."""
    if not identifier:
        return False
    # \w is Unicode-aware, matching Python's own identifier alphabet (`größe` is one token).
    pattern = rf"(?<!\w){re.escape(identifier)}(?!\w)"
    return re.search(pattern, text) is not None


def symbol_identifiers(symbol: CandidateSymbol) -> tuple[str, ...]:
    """The exact names evidence may use to refer to this symbol."""
    names = [symbol.name]
    if symbol.qualified_name_hint and symbol.qualified_name_hint != symbol.name:
        names.append(symbol.qualified_name_hint)
    return tuple(names)


def module_file(dotted: str, repo_files: frozenset[str]) -> str | None:
    """The real file a dotted name lives in (`a.b.f` / `a.b.Cls.m` -> `a/b.py`), else None.

    Only the exact module is accepted: `module.func`, or `module.Class.method` when the
    second-to-last part is a class name. Never walks up to a parent package, so a hint
    whose module is missing stays unresolved instead of landing on `app/__init__.py`.
    """
    parts = dotted.split(".")
    modules = [parts[:-1]]
    if len(parts) >= 3 and parts[-2][:1].isupper():
        modules.append(parts[:-2])
    for module in modules:
        base = "/".join(module)
        for path in (f"{base}.py", f"{base}/__init__.py"):
            if base and path in repo_files:
                return path
    return None


def resolve_target_file(
    symbol: CandidateSymbol,
    repo_files: frozenset[str],
    named_files: Iterable[str],
    resolver_files: Iterable[str],
) -> str | None:
    """A real file for `symbol`, or None when there isn't exactly one defensible choice.

    Order: the symbol's own dotted module path; else the single existing non-test file
    the issue names; else, only if the issue names no path at all, the single non-test
    resolver candidate. A named-but-missing path is never "corrected" by the resolver.
    """
    for name in reversed(symbol_identifiers(symbol)):
        if "." in name and (path := module_file(name, repo_files)):
            return path
    named = list(named_files)
    pool = named if named else list(resolver_files)
    choices = {p for p in pool if p in repo_files and not is_test_path(p)}
    return choices.pop() if len(choices) == 1 else None


def delete_targets(
    requested_actions: Iterable[str], named_files: Sequence[str], repo_files: frozenset[str]
) -> set[str]:
    """Files to DELETE: only when the issue names exactly one path and it exists.

    The understander does not tie actions to files, so with several named paths
    ("delete a.py and update b.py") we cannot tell which to delete and leave it to the LLM.
    """
    if "delete" not in requested_actions or len(set(named_files)) != 1:
        return set()
    return {p for p in named_files if p in repo_files}


def dedupe(hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
    """One hypothesis per (symbol, file, action), keeping the strongest issue mention.

    Duplicate mentions (title and description) would otherwise tie and route as ambiguous.
    """
    best: dict[tuple[str, str | None, str], Hypothesis] = {}
    for hyp in hypotheses:
        key = (hyp.target_symbol, hyp.target_file, hyp.proposed_action)
        if key not in best or _mention_strength(hyp) > _mention_strength(best[key]):
            best[key] = hyp
    return list(best.values())


def _mention_strength(hyp: Hypothesis) -> float:
    return max((e.confidence for e in hyp.supporting_evidence), default=0.0)


def tests_for(source_file: str, tests: Iterable[str]) -> list[str]:
    """Tests named after `source_file` by pytest convention (`test_x.py` / `x_test.py`)."""
    stem = PurePosixPath(source_file).stem
    names = {f"test_{stem}.py", f"{stem}_test.py"}
    return [t for t in tests if PurePosixPath(t).name in names]


class EvidenceInvestigator:
    """
    Gathers grounded evidence for an issue and hands the graph to the confidence gate.
    """

    def __init__(
        self,
        brain: RepositoryBrain | None = None,
        confidence_gate: ConfidenceGate | None = None,
    ) -> None:
        # The default brain is in-memory and empty: offline-safe, contributes nothing.
        self._brain = brain or RepositoryBrain()
        self._confidence_gate = confidence_gate or ConfidenceGate()

    async def investigate(
        self,
        understanding: IssueUnderstanding,
        repository_id: uuid.UUID,
        *,
        repo_files: frozenset[str],
        candidate_files: Sequence[str] = (),
    ) -> EvidenceGraph:
        """Builds hypotheses with exactly-matched evidence and routes the graph."""
        graph = EvidenceGraph.create(repository_id=repository_id)
        issue_files = {
            f.file_path: f.confidence
            for f in understanding.affected_files
            if f.file_path in repo_files
        }
        # Every path the issue names, existing or not: naming a missing path still blocks
        # the resolver fallback, so a typo is never silently "corrected".
        named_files = [f.file_path for f in understanding.affected_files] + list(
            understanding.unresolved_paths
        )
        resolver_files = [p for p in candidate_files if p in repo_files]
        tests = [t for t in understanding.relevant_tests if t in repo_files]
        memories = await self._recall(understanding, repository_id)

        deleted = delete_targets(understanding.requested_actions, named_files, repo_files)
        hypotheses = dedupe(
            h
            for h in (
                self._symbol_hypothesis(sym, repo_files, named_files, resolver_files)
                for sym in understanding.affected_symbols
            )
            if h.target_file not in deleted
        )
        hypotheses += [
            Hypothesis.create(target_symbol="", target_file=path, proposed_action="DELETE")
            for path in sorted(deleted)
        ]

        for hyp in hypotheses:
            hyp.supporting_evidence.extend(
                self._file_evidence(hyp, issue_files, resolver_files)
                + self._test_evidence(hyp, tests)
                + self._brain_evidence(hyp, memories)
            )
            graph.evidence_pool.extend(hyp.supporting_evidence)
        graph.hypotheses.extend(hypotheses)

        return self._confidence_gate.evaluate(graph)

    async def _recall(
        self, understanding: IssueUnderstanding, repository_id: uuid.UUID
    ) -> list[RepositoryMemory]:
        return await self._brain.recall_memories(
            repository_id=repository_id,
            query_text=f"{understanding.raw_title} {understanding.raw_description}",
            threshold=BRAIN_RECALL_THRESHOLD,
        )

    @staticmethod
    def _symbol_hypothesis(
        symbol: CandidateSymbol,
        repo_files: frozenset[str],
        named_files: list[str],
        resolver_files: list[str],
    ) -> Hypothesis:
        """MODIFY hypothesis for an issue symbol, supported by its mention in the issue."""
        target = resolve_target_file(symbol, repo_files, named_files, resolver_files)
        hyp = Hypothesis.create(target_symbol=symbol.name, target_file=target)
        hyp.supporting_evidence.append(
            Evidence(
                source_type=EvidenceSource.EXACT_SYMBOL,
                description=f"Symbol named in issue: {symbol.name}",
                confidence=symbol.confidence,
                relevance=MENTION_RELEVANCE,
            )
        )
        return hyp

    @staticmethod
    def _file_evidence(
        hyp: Hypothesis, issue_files: dict[str, float], resolver_files: list[str]
    ) -> list[Evidence]:
        path = hyp.target_file
        if path in issue_files:
            return [
                Evidence(
                    source_type=EvidenceSource.FILE_MATCH,
                    description=f"Issue names existing file: {path}",
                    confidence=issue_files[path],
                    relevance=ISSUE_FILE_RELEVANCE,
                )
            ]
        if path in resolver_files:
            return [
                Evidence(
                    source_type=EvidenceSource.FILE_MATCH,
                    description=f"Candidate resolver ranked file: {path}",
                    confidence=RESOLVER_FILE_CONFIDENCE,
                    relevance=RESOLVER_FILE_RELEVANCE,
                )
            ]
        return []

    @staticmethod
    def _test_evidence(hyp: Hypothesis, tests: list[str]) -> list[Evidence]:
        if hyp.target_file is None:
            return []
        return [
            Evidence(
                source_type=EvidenceSource.TEST_MAPPING,
                description=f"Test suite for {hyp.target_file}: {test}",
                confidence=TEST_CONFIDENCE,
                relevance=TEST_RELEVANCE,
            )
            for test in tests_for(hyp.target_file, tests)
        ]

    @staticmethod
    def _brain_evidence(hyp: Hypothesis, memories: list[RepositoryMemory]) -> list[Evidence]:
        """Past resolutions that changed this file or name this symbol exactly."""
        return [
            Evidence(
                source_type=EvidenceSource.REPOSITORY_BRAIN,
                source_id=mem.memory_id,
                description=f"Historical resolution memory: {mem.issue_text[:80]}",
                confidence=BRAIN_CONFIDENCE,
                relevance=BRAIN_RELEVANCE,
            )
            for mem in memories
            if (hyp.target_file is not None and hyp.target_file in mem.files_changed)
            or mentions_identifier(mem.issue_text, hyp.target_symbol)
        ]
