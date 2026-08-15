"""
Redis Key Builder

Centralized key construction for all Redis keys used across Forge.
Prevents key format duplication and ensures consistent namespacing.
"""


class RedisKeys:
    """
    Generates standardized Redis key strings for Forge subsystems.
    """

    PREFIX = "forge"

    # ── Embedding Cache ──────────────────────────────────────────────
    @staticmethod
    def embedding(
        provider: str,
        model: str,
        dimension: int,
        content_hash: str,
    ) -> str:
        """
        Key for a cached embedding vector.

        Format: forge:embedding:{provider}:{model}:{dimension}:{content_hash}
        Example: forge:embedding:voyage:voyage-code-3:1024:a1b2c3...
        """
        return f"forge:embedding:{provider}:{model}:{dimension}:{content_hash}"

    # ── Context Cache ────────────────────────────────────────────────
    @staticmethod
    def context(
        repo_id: str,
        symbol_id: str,
        context_version: str = "v1",
    ) -> str:
        """
        Key for a cached RepositoryContext payload.

        Format: forge:context:{repo_id}:{symbol_id}:{context_version}
        """
        return f"forge:context:{repo_id}:{symbol_id}:{context_version}"

    # ── Query Cache ──────────────────────────────────────────────────
    @staticmethod
    def query(
        repo_id: str,
        query_type: str,
        query_hash: str,
        context_version: str = "v1",
    ) -> str:
        """
        Key for a cached graph/query result.

        Format: forge:query:{repo_id}:{query_type}:{query_hash}:{context_version}
        """
        return f"forge:query:{repo_id}:{query_type}:{query_hash}:{context_version}"

    # ── Distributed Indexing Lock ────────────────────────────────────
    @staticmethod
    def index_lock(repo_id: str) -> str:
        """
        Key for a distributed indexing lock on a repository.

        Format: forge:lock:index:{repo_id}
        """
        return f"forge:lock:index:{repo_id}"

    # ── Job State ────────────────────────────────────────────────────
    @staticmethod
    def job_state(job_id: str) -> str:
        """
        Key for tracking indexing job state.

        Format: forge:job:state:{job_id}
        """
        return f"forge:job:state:{job_id}"

    # ── Progress Events ──────────────────────────────────────────────
    @staticmethod
    def repo_events(repo_id: str) -> str:
        """
        Redis Stream / PubSub channel for repository indexing events.

        Format: forge:events:repo:{repo_id}
        """
        return f"forge:events:repo:{repo_id}"
