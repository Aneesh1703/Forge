"""
Candidate Context Resolution Package for Forge Engine.
Provides multi-signal evidence scoring, candidate discovery, and context assembly.
"""

from app.agents.candidate.models import CandidateContext, CandidateFile, CandidateScore
from app.agents.candidate.resolver import CandidateContextResolver
from app.agents.candidate.scoring import CandidateScorer

__all__ = [
    "CandidateContext",
    "CandidateFile",
    "CandidateScore",
    "CandidateScorer",
    "CandidateContextResolver",
]
