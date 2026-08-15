"""
Evidence & Hypothesis Domain Models

Defines EvidenceSource, Evidence, Hypothesis, InvestigationBudget, and EvidenceGraph.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum


class EvidenceSource(str, Enum):
    """Source type of a gathered repository evidence item."""

    REPOSITORY_BRAIN = "repository_brain"
    AST_GRAPH = "ast_graph"
    EXACT_SYMBOL = "exact_symbol"
    VECTOR_HIT = "vector_hit"
    TEST_MAPPING = "test_mapping"


@dataclass(frozen=True)
class Evidence:
    """
    Individual item of evidence gathered from the repository.
    """

    source_type: EvidenceSource
    description: str
    confidence: float
    relevance: float
    cost: float = 0.0
    source_id: uuid.UUID | None = None
    is_contradiction: bool = False


@dataclass
class Hypothesis:
    """
    Hypothesis proposing a specific modification target or architectural action.
    """

    hypothesis_id: uuid.UUID
    target_symbol: str
    target_file: str | None = None
    proposed_action: str = "MODIFY"
    supporting_evidence: list[Evidence] = field(default_factory=list)
    contradicting_evidence: list[Evidence] = field(default_factory=list)
    computed_confidence: float = 0.0

    @classmethod
    def create(
        cls,
        target_symbol: str,
        target_file: str | None = None,
        proposed_action: str = "MODIFY",
    ) -> "Hypothesis":
        return cls(
            hypothesis_id=uuid.uuid4(),
            target_symbol=target_symbol,
            target_file=target_file,
            proposed_action=proposed_action,
        )


@dataclass
class InvestigationBudget:
    """
    Cost & resource ceiling budget for evidence exploration.
    """

    max_llm_calls: int = 2
    max_context_tokens: int = 5000
    max_vector_queries: int = 5
    max_postgres_queries: int = 50


@dataclass
class EvidenceGraph:
    """
    Ranked evidence graph linking hypotheses, symbols, files, and confidence metrics.
    """

    graph_id: uuid.UUID
    repository_id: uuid.UUID
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence_pool: list[Evidence] = field(default_factory=list)
    overall_confidence: float = 0.0
    tokens_used: int = 0
    llm_calls_made: int = 0

    @classmethod
    def create(cls, repository_id: uuid.UUID) -> "EvidenceGraph":
        return cls(
            graph_id=uuid.uuid4(),
            repository_id=repository_id,
        )
