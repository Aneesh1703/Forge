"""
Confidence Gate Evaluator

Scores hypotheses from independent evidence sources and decides whether the evidence is
strong enough for deterministic planning or must be routed to the LLM planner.
"""

from collections.abc import Iterable, Mapping

from app.agents.evidence.models import Evidence, EvidenceGraph, EvidenceSource, Hypothesis

# A symbol that is only named in the issue text proves nothing about the code on its own.
MENTION_SOURCES = frozenset({EvidenceSource.EXACT_SYMBOL})
MENTION_ONLY_FACTOR = 0.5
# Without two independent sources or a real file, a hypothesis is at best a guess.
SINGLE_SOURCE_CAP = 0.6
# Top two hypotheses closer than this are indistinguishable.
AMBIGUITY_MARGIN = 0.1


def evidence_strength(evidence: Evidence) -> float:
    """Strength of one evidence item, clamped to [0, 1]."""
    return min(1.0, max(0.0, evidence.confidence * evidence.relevance))


def best_per_source(evidence: Iterable[Evidence]) -> dict[EvidenceSource, float]:
    """Strongest item per source type, so repeating one source can't inflate the score."""
    best: dict[EvidenceSource, float] = {}
    for e in evidence:
        best[e.source_type] = max(best.get(e.source_type, 0.0), evidence_strength(e))
    return best


def noisy_or(strengths: Iterable[float]) -> float:
    """Probability that at least one independent source is right: 1 - prod(1 - e)."""
    miss = 1.0
    for e in strengths:
        miss *= 1.0 - e
    return 1.0 - miss


def support_score(per_source: Mapping[EvidenceSource, float]) -> float:
    """Noisy-OR over source types; mention-only support counts at half strength."""
    if per_source and per_source.keys() <= MENTION_SOURCES:
        return noisy_or(e * MENTION_ONLY_FACTOR for e in per_source.values())
    return noisy_or(per_source.values())


def hypothesis_confidence(hypothesis: Hypothesis) -> float:
    """Final confidence: capped support, reduced by the strongest contradiction."""
    per_source = best_per_source(hypothesis.supporting_evidence)
    score = support_score(per_source)
    if len(per_source) < 2 or hypothesis.target_file is None:
        score = min(score, SINGLE_SOURCE_CAP)
    k = max((evidence_strength(e) for e in hypothesis.contradicting_evidence), default=0.0)
    return score * (1.0 - k)


def routing_reason(ranked: list[Hypothesis], threshold: float) -> str:
    """Why the graph is (in)sufficient; `ranked` is sorted by confidence, best first."""
    if not ranked:
        return "no_hypotheses"
    top = ranked[0]
    if len(ranked) > 1 and top.computed_confidence - ranked[1].computed_confidence < (
        AMBIGUITY_MARGIN
    ):
        return "ambiguous_top2"
    if len(best_per_source(top.supporting_evidence)) < 2:
        return "single_source"
    if top.computed_confidence < threshold:
        return "below_threshold"
    return "sufficient"


class ConfidenceGate:
    """
    Single routing entry point: decides whether an EvidenceGraph supports deterministic
    planning. The threshold lives only here.
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self.threshold = threshold

    def evaluate(self, graph: EvidenceGraph) -> EvidenceGraph:
        """Scores and ranks hypotheses, writes the routing verdict onto `graph`, returns it."""
        for hyp in graph.hypotheses:
            hyp.computed_confidence = hypothesis_confidence(hyp)
        graph.hypotheses.sort(key=lambda h: h.computed_confidence, reverse=True)

        ranked = graph.hypotheses
        graph.top_confidence = ranked[0].computed_confidence if ranked else 0.0
        graph.runner_up_confidence = ranked[1].computed_confidence if len(ranked) > 1 else 0.0
        graph.overall_confidence = graph.top_confidence
        graph.routing_reason = routing_reason(ranked, self.threshold)
        graph.is_sufficient = graph.routing_reason == "sufficient"
        return graph
