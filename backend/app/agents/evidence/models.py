"""
Evidence & Hypothesis Domain Models

Defines EvidenceSource, Evidence, Hypothesis, InvestigationBudget, and EvidenceGraph.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceSource(str, Enum):
    """Source type of a gathered repository evidence item."""

    REPOSITORY_BRAIN = "repository_brain"
    AST_GRAPH = "ast_graph"
    EXACT_SYMBOL = "exact_symbol"
    VECTOR_HIT = "vector_hit"
    TEST_MAPPING = "test_mapping"
    FILE_MATCH = "file_match"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type.value,
            "description": self.description,
            "confidence": self.confidence,
            "relevance": self.relevance,
            "is_contradiction": self.is_contradiction,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": str(self.hypothesis_id),
            "target_symbol": self.target_symbol,
            "target_file": self.target_file,
            "proposed_action": self.proposed_action,
            "computed_confidence": self.computed_confidence,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.to_dict() for e in self.contradicting_evidence],
        }


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
    # Routing verdict written by the confidence gate: is the evidence strong enough for
    # deterministic planning, and if not, why not.
    is_sufficient: bool = False
    routing_reason: str = ""
    top_confidence: float = 0.0
    runner_up_confidence: float = 0.0

    @classmethod
    def create(cls, repository_id: uuid.UUID) -> "EvidenceGraph":
        return cls(
            graph_id=uuid.uuid4(),
            repository_id=repository_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for JobState and plan.json."""
        return {
            "graph_id": str(self.graph_id),
            "overall_confidence": self.overall_confidence,
            "is_sufficient": self.is_sufficient,
            "routing_reason": self.routing_reason,
            "top_confidence": self.top_confidence,
            "runner_up_confidence": self.runner_up_confidence,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
        }
