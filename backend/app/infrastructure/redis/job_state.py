"""
Indexing Job State Management

Provides structured job state tracking stored in Redis (`forge:job:state:{job_id}`).
Allows background workers and UI clients to monitor live indexing progress and failures.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.redis.keys import RedisKeys


@dataclass
class IndexingJobState:
    """
    Structured state model for a repository indexing job.
    """

    job_id: str
    repo_id: str
    status: str = "pending"  # pending, running, completed, failed
    progress_pct: float = 0.0
    current_phase: str = "initialized"
    processed_files: int = 0
    total_files: int = 0
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexingJobState":
        return cls(
            job_id=data["job_id"],
            repo_id=data["repo_id"],
            status=data.get("status", "pending"),
            progress_pct=float(data.get("progress_pct", 0.0)),
            current_phase=data.get("current_phase", "initialized"),
            processed_files=int(data.get("processed_files", 0)),
            total_files=int(data.get("total_files", 0)),
            error_message=data.get("error_message"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


class JobStateManager:
    """
    Manager for persisting and updating indexing job states in Redis.
    """

    DEFAULT_TTL_SECONDS = 86400  # 24 hours

    def __init__(self, cache: RedisCache, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._cache = cache
        self._ttl = ttl_seconds

    async def create_job(self, job_id: str, repo_id: str, total_files: int = 0) -> IndexingJobState:
        """
        Initialize a new indexing job state in Redis.
        """
        state = IndexingJobState(
            job_id=job_id,
            repo_id=repo_id,
            status="pending",
            total_files=total_files,
        )
        key = RedisKeys.job_state(job_id)
        await self._cache.set_json(key, state.to_dict(), ttl_seconds=self._ttl)
        return state

    async def get_job_state(self, job_id: str) -> IndexingJobState | None:
        """
        Retrieve existing job state from Redis.
        """
        key = RedisKeys.job_state(job_id)
        raw = await self._cache.get_json(key)
        if raw and isinstance(raw, dict):
            return IndexingJobState.from_dict(raw)
        return None

    async def update_progress(
        self,
        job_id: str,
        current_phase: str,
        processed_files: int,
        total_files: int | None = None,
    ) -> IndexingJobState | None:
        """
        Update progress percentage and current phase for a job.
        """
        state = await self.get_job_state(job_id)
        if not state:
            return None

        state.current_phase = current_phase
        state.processed_files = processed_files
        if total_files is not None and total_files > 0:
            state.total_files = total_files

        if state.total_files > 0:
            state.progress_pct = min(100.0, round((processed_files / state.total_files) * 100.0, 2))

        state.status = "running"
        state.updated_at = time.time()

        key = RedisKeys.job_state(job_id)
        await self._cache.set_json(key, state.to_dict(), ttl_seconds=self._ttl)
        return state

    async def mark_completed(self, job_id: str) -> IndexingJobState | None:
        """
        Mark job as successfully completed.
        """
        state = await self.get_job_state(job_id)
        if not state:
            return None

        state.status = "completed"
        state.progress_pct = 100.0
        state.current_phase = "finished"
        state.updated_at = time.time()

        key = RedisKeys.job_state(job_id)
        await self._cache.set_json(key, state.to_dict(), ttl_seconds=self._ttl)
        return state

    async def mark_failed(self, job_id: str, error_message: str) -> IndexingJobState | None:
        """
        Mark job as failed with error details.
        """
        state = await self.get_job_state(job_id)
        if not state:
            return None

        state.status = "failed"
        state.error_message = error_message
        state.current_phase = "failed"
        state.updated_at = time.time()

        key = RedisKeys.job_state(job_id)
        await self._cache.set_json(key, state.to_dict(), ttl_seconds=self._ttl)
        return state
