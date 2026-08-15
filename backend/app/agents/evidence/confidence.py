"""
Confidence Gate Evaluator

Evaluates aggregate hypothesis confidence scores and counter-evidence contradiction penalties.
"""

from app.agents.evidence.models import EvidenceGraph, Hypothesis


class ConfidenceGate:
    """
    Confidence evaluation engine determining whether an EvidenceGraph has sufficient
    high-confidence evidence to proceed to LLM plan generation.
    """

    def evaluate(
        self,
        graph: EvidenceGraph,
        threshold: float = 0.85,
        contradiction_penalty_factor: float = 2.0,
    ) -> tuple[bool, float]:
        """
        Evaluates overall confidence of hypotheses in graph against threshold.
        """
        if not graph.hypotheses:
            graph.overall_confidence = 0.0
            return (False, 0.0)

        max_confidence = 0.0

        for hyp in graph.hypotheses:
            conf = self.calculate_hypothesis_confidence(
                hyp, penalty_factor=contradiction_penalty_factor
            )
            hyp.computed_confidence = conf
            if conf > max_confidence:
                max_confidence = conf

        graph.overall_confidence = max_confidence
        is_sufficient = max_confidence >= threshold
        return (is_sufficient, max_confidence)

    def calculate_hypothesis_confidence(
        self,
        hypothesis: Hypothesis,
        penalty_factor: float = 2.0,
    ) -> float:
        """
        Calculates confidence score for a single hypothesis.
        """
        support_score = sum(e.confidence * e.relevance for e in hypothesis.supporting_evidence)
        contradict_score = sum(
            e.confidence * e.relevance for e in hypothesis.contradicting_evidence
        )

        if support_score == 0.0 and contradict_score == 0.0:
            return 0.0

        denominator = support_score + (penalty_factor * contradict_score) + 0.05
        return min(1.0, max(0.0, support_score / denominator))
