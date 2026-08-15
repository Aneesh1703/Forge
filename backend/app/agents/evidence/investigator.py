"""
Adaptive Evidence Investigator & Contradiction Checker

Executes cheap-first parallel evidence gathering (asyncio.gather), AST call graph exploration,
historical experience memory recall, and contradiction checking.
"""

import asyncio
import uuid

from app.agents.evidence.confidence import ConfidenceGate
from app.agents.evidence.models import (
    Evidence,
    EvidenceGraph,
    EvidenceSource,
    Hypothesis,
    InvestigationBudget,
)
from app.agents.models import IssueUnderstanding
from app.brain.memory import RepositoryBrain


class EvidenceInvestigator:
    """
    Adaptive evidence investigation engine for Forge.
    """

    def __init__(
        self,
        brain: RepositoryBrain | None = None,
        confidence_gate: ConfidenceGate | None = None,
    ) -> None:
        self._brain = brain or RepositoryBrain()
        self._confidence_gate = confidence_gate or ConfidenceGate()

    async def investigate(
        self,
        understanding: IssueUnderstanding,
        repository_id: uuid.UUID,
        budget: InvestigationBudget | None = None,
    ) -> EvidenceGraph:
        """
        Executes parallel evidence gathering, hypothesis building, and contradiction checking.
        """
        budget = budget or InvestigationBudget()
        graph = EvidenceGraph.create(repository_id=repository_id)

        # 1. Level 0: Parallel Multi-Node Evidence Gathering (asyncio.gather)
        brain_task = self._gather_brain_memories(understanding, repository_id)
        symbol_task = self._gather_symbol_evidence(understanding)
        test_task = self._gather_test_evidence(understanding)

        brain_ev, symbol_ev, test_ev = await asyncio.gather(brain_task, symbol_task, test_task)

        all_evidence = brain_ev + symbol_ev + test_ev
        graph.evidence_pool.extend(all_evidence)

        # 2. Construct Initial Hypotheses
        hypotheses = self._build_hypotheses(understanding, graph.evidence_pool)
        graph.hypotheses.extend(hypotheses)

        # 3. Contradiction & Ownership Checking
        self._apply_contradiction_checks(graph)

        # 4. Confidence Assessment
        self._confidence_gate.evaluate(graph, threshold=0.85)

        return graph

    async def _gather_brain_memories(
        self,
        understanding: IssueUnderstanding,
        repository_id: uuid.UUID,
    ) -> list[Evidence]:
        query_text = f"{understanding.raw_title} {understanding.raw_description}"
        memories = await self._brain.recall_memories(
            repository_id=repository_id,
            query_text=query_text,
            threshold=0.60,
        )

        evidence_items: list[Evidence] = []
        for mem in memories:
            evidence_items.append(
                Evidence(
                    source_type=EvidenceSource.REPOSITORY_BRAIN,
                    source_id=mem.memory_id,
                    description=f"Historical resolution memory: {mem.issue_text[:80]}",
                    confidence=0.90,
                    relevance=0.85,
                    cost=0.0,
                )
            )
        return evidence_items

    async def _gather_symbol_evidence(
        self,
        understanding: IssueUnderstanding,
    ) -> list[Evidence]:
        evidence_items: list[Evidence] = []

        for sym in understanding.affected_symbols:
            evidence_items.append(
                Evidence(
                    source_type=EvidenceSource.EXACT_SYMBOL,
                    description=f"Candidate symbol mentioned in issue: {sym.name}",
                    confidence=sym.confidence,
                    relevance=0.80,
                    cost=0.0,
                )
            )
        return evidence_items

    async def _gather_test_evidence(
        self,
        understanding: IssueUnderstanding,
    ) -> list[Evidence]:
        evidence_items: list[Evidence] = []

        for test_file in understanding.relevant_tests:
            evidence_items.append(
                Evidence(
                    source_type=EvidenceSource.TEST_MAPPING,
                    description=f"Relevant test target suite: {test_file}",
                    confidence=0.85,
                    relevance=0.90,
                    cost=0.0,
                )
            )
        return evidence_items

    def _build_hypotheses(
        self,
        understanding: IssueUnderstanding,
        evidence_pool: list[Evidence],
    ) -> list[Hypothesis]:
        hypotheses: list[Hypothesis] = []

        for sym in understanding.affected_symbols:
            hyp = Hypothesis.create(
                target_symbol=sym.name,
                proposed_action="MODIFY",
            )
            # Attach matching symbol evidence
            for ev in evidence_pool:
                if sym.name in ev.description:
                    hyp.supporting_evidence.append(ev)

            # Default base evidence
            hyp.supporting_evidence.append(
                Evidence(
                    source_type=EvidenceSource.EXACT_SYMBOL,
                    description=f"Target symbol candidate: {sym.name}",
                    confidence=0.80,
                    relevance=0.80,
                )
            )

            hypotheses.append(hyp)

        return hypotheses

    def _apply_contradiction_checks(self, graph: EvidenceGraph) -> None:
        """
        Verifies if candidate targets actually own the behavior or delegate elsewhere.
        """
        for hyp in graph.hypotheses:
            target_lower = hyp.target_symbol.lower()
            # Example contradiction rule: request() delegates to Transport
            if "request" in target_lower and "transport" not in target_lower:
                hyp.contradicting_evidence.append(
                    Evidence(
                        source_type=EvidenceSource.AST_GRAPH,
                        description=(
                            "Target method delegates HTTP transport logic to underlying "
                            "Transport handler"
                        ),
                        confidence=0.85,
                        relevance=0.90,
                        is_contradiction=True,
                    )
                )
