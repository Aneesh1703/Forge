"""
LangGraph Stateful Workflow Engine for Forge Pipeline.
Provides StateGraph node transitions, checkpointing, and history snapshotting.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar, cast


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


@dataclass
class WorkflowState:
    """State payload passed across nodes in the LangGraph StateGraph pipeline."""

    job_id: str
    issue_prompt: str
    repo_root: Path
    candidate_files: list[str] = field(default_factory=list)
    unified_context: str = ""
    target_file: str = ""
    replacement_code: str = ""
    code_patch: dict[str, Any] | None = None
    repair_attempts: int = 0
    max_repair_attempts: int = 3
    is_valid_patch: bool = False
    test_passed: bool = False
    error_feedback: str = ""
    gate_approved: bool = False
    current_node: str = "START"
    status: NodeStatus = NodeStatus.PENDING


T = TypeVar("T")


class ForgeStateGraph(Generic[T]):
    """Stateful DAG workflow engine following LangGraph semantics for autonomous repair."""

    def __init__(self) -> None:
        self.nodes: dict[str, Callable[[Any], Any]] = {}
        self.edges: dict[str, str] = {}
        self.conditional_edges: dict[str, tuple[Callable[[Any], str], dict[str, str]]] = {}
        self.history: list[Any] = []

    def add_node(self, name: str, func: Callable[[Any], Any]) -> None:
        """Registers a pipeline step node."""
        self.nodes[name] = func

    def add_edge(self, source: str, target: str) -> None:
        """Registers a direct edge between two nodes."""
        self.edges[source] = target

    def add_conditional_edges(
        self,
        source: str,
        condition_func: Callable[[Any], str],
        mapping: dict[str, str],
    ) -> None:
        """Registers a conditional branch edge."""
        self.conditional_edges[source] = (condition_func, mapping)

    def execute(self, initial_state: T) -> T:
        """Executes state graph node transitions with checkpointing until END."""
        state = initial_state
        curr = "START"
        self.history.append(deepcopy(state))

        while curr != "END":
            status_attr = getattr(state, "status", None)
            if status_attr == NodeStatus.WAITING_APPROVAL:
                break

            setattr(state, "current_node", curr)
            if curr in self.nodes:
                state = self.nodes[curr](state)
                self.history.append(deepcopy(state))

            status_attr = getattr(state, "status", None)
            if status_attr in (NodeStatus.FAILED, NodeStatus.WAITING_APPROVAL):
                break

            # Resolve next node
            if curr in self.conditional_edges:
                cond_func, mapping = self.conditional_edges[curr]
                branch_key = cond_func(state)
                curr = mapping.get(branch_key, "END")
            elif curr in self.edges:
                curr = self.edges[curr]
            else:
                break

        return state

    def rewind(self, steps: int = 1) -> T | None:
        """Rewinds the state graph back N checkpoint steps."""
        if not self.history:
            return None
        target_idx = max(0, len(self.history) - 1 - steps)
        res: T = cast(Any, deepcopy(self.history[target_idx]))
        return res
