"""
Forge Embedding Engine

Provides multi-provider embedding abstractions and incremental batch services.
"""

from app.embeddings.base import BaseEmbeddingProvider
from app.embeddings.cached_service import CachedEmbeddingService
from app.embeddings.mock import MockEmbeddingProvider
from app.embeddings.ollama import OllamaEmbeddingProvider
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.service import EmbeddedChunkResult, EmbeddingService
from app.embeddings.voyage import VoyageEmbeddingProvider

__all__ = [
    "BaseEmbeddingProvider",
    "CachedEmbeddingService",
    "EmbeddedChunkResult",
    "EmbeddingService",
    "MockEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "VoyageEmbeddingProvider",
]
