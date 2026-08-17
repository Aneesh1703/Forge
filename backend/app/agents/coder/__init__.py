"""
Phase 9A: Autonomous Coding Agent Package
"""

from app.agents.coder.coder import CodingAgent
from app.agents.coder.complexity import ComplexityScorer
from app.agents.coder.context import MinimalContextBuilder
from app.agents.coder.diagnostics import FailureDiagnosis, TracebackFrame, TracebackParser
from app.agents.coder.models import (
    CodeHunk,
    CodePatch,
    ComplexityScore,
    ExecutionPolicy,
    ModelTier,
    SymbolTarget,
)
from app.agents.coder.patch_builder import PatchApplicationError, PatchBuilder
from app.agents.coder.repair import AutoFixLoop, RepairState
from app.agents.coder.repo_gate import FinalDeterministicRepositoryGate, FinalGateResult
from app.agents.coder.reviewer import FinalReviewerAgent, ReviewDecision, ReviewResult
from app.agents.coder.validator import PatchSafetyGate, PatchValidationResult

__all__ = [
    "AutoFixLoop",
    "CodingAgent",
    "ComplexityScore",
    "ComplexityScorer",
    "CodeHunk",
    "CodePatch",
    "ExecutionPolicy",
    "FailureDiagnosis",
    "FinalDeterministicRepositoryGate",
    "FinalGateResult",
    "FinalReviewerAgent",
    "MinimalContextBuilder",
    "ModelTier",
    "PatchApplicationError",
    "PatchBuilder",
    "PatchSafetyGate",
    "PatchValidationResult",
    "RepairState",
    "ReviewDecision",
    "ReviewResult",
    "SymbolTarget",
    "TracebackFrame",
    "TracebackParser",
]
