"""
Repository Brain Memory Engine

Stores and retrieves historical engineering issue resolutions, evidence graphs, and plans
to enable zero-token experience recall.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.repository_memory_orm import RepositoryMemoryORM


@dataclass(frozen=True)
class RepositoryMemory:
    """
    Domain object representing a historical engineering issue resolution memory.
    """

    memory_id: uuid.UUID
    repository_id: uuid.UUID
    issue_text: str
    intent: str
    evidence_graph_snapshot: dict[str, Any] = field(default_factory=dict)
    resolved_plan: dict[str, Any] = field(default_factory=dict)
    files_changed: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_orm(cls, orm: RepositoryMemoryORM) -> "RepositoryMemory":
        """Converts ORM record into domain DTO."""
        return cls(
            memory_id=orm.id,
            repository_id=orm.repository_id,
            issue_text=orm.issue_text,
            intent=orm.intent,
            evidence_graph_snapshot=orm.evidence_graph_snapshot or {},
            resolved_plan=orm.resolved_plan or {},
            files_changed=orm.files_changed or [],
            created_at=orm.created_at,
        )


class RepositoryBrain:
    """
    Repository Brain persistence & historical memory recall engine.
    """

    def __init__(self, in_memory_store: list[RepositoryMemory] | None = None) -> None:
        self._in_memory_store: list[RepositoryMemory] = in_memory_store or []

    async def save_memory(
        self,
        repository_id: uuid.UUID,
        issue_text: str,
        intent: str,
        evidence_graph: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        files_changed: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> RepositoryMemory:
        """
        Persists a solved engineering issue memory.
        """
        memory = RepositoryMemory(
            memory_id=uuid.uuid4(),
            repository_id=repository_id,
            issue_text=issue_text.strip(),
            intent=intent,
            evidence_graph_snapshot=evidence_graph or {},
            resolved_plan=plan or {},
            files_changed=files_changed or [],
            created_at=datetime.now(timezone.utc),
        )

        if session is not None:
            orm = RepositoryMemoryORM(
                id=memory.memory_id,
                repository_id=memory.repository_id,
                issue_text=memory.issue_text,
                intent=memory.intent,
                evidence_graph_snapshot=memory.evidence_graph_snapshot,
                resolved_plan=memory.resolved_plan,
                files_changed=memory.files_changed,
                created_at=memory.created_at,
            )
            session.add(orm)
            await session.flush()

        self._in_memory_store.append(memory)
        return memory

    async def recall_memories(
        self,
        repository_id: uuid.UUID,
        query_text: str,
        threshold: float = 0.60,
        session: AsyncSession | None = None,
    ) -> list[RepositoryMemory]:
        """
        Searches historical memories for matching experience patterns.
        """
        query_words = set(query_text.lower().split())
        matched: list[RepositoryMemory] = []

        # 1. DB Lookup if session provided
        if session is not None:
            stmt = select(RepositoryMemoryORM).where(
                RepositoryMemoryORM.repository_id == repository_id
            )
            result = await session.execute(stmt)
            for row in result.scalars().all():
                mem = RepositoryMemory.from_orm(row)
                if mem not in self._in_memory_store:
                    self._in_memory_store.append(mem)

        # 2. Match calculation
        for mem in self._in_memory_store:
            if mem.repository_id != repository_id:
                continue

            mem_words = set(mem.issue_text.lower().split())
            if not mem_words or not query_words:
                continue

            intersection = query_words.intersection(mem_words)
            similarity = len(intersection) / float(max(len(query_words), len(mem_words)))

            if similarity >= threshold:
                matched.append(mem)

        return matched
