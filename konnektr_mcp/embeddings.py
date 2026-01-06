# konnektr_mcp/embeddings.py
"""
Embedding service for generating vector embeddings from text.

Supports multiple providers:
- OpenAI (default)
- Azure OpenAI
- Google Gemini
"""
import logging
from abc import ABC, abstractmethod
from enum import Enum
from functools import lru_cache
from typing import Optional

from openai import AsyncOpenAI, AsyncAzureOpenAI
from google import genai
from google.genai.types import EmbedContentConfig

logger = logging.getLogger(__name__)


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"


class EmbeddingService(ABC):
    """Abstract base class for embedding services."""

    @abstractmethod
    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate an embedding vector for the given text."""
        pass

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embedding vectors for multiple texts (batch operation)."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of the embeddings."""
        pass

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
        pass


class OpenAIEmbeddingService(EmbeddingService):
    """OpenAI embedding service using text-embedding-3-small."""

    DEFAULT_MODEL = "text-embedding-3-small"
    DEFAULT_DIMENSIONS = 1536

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the OpenAI embedding service.

        Args:
            api_key: OpenAI API key
            model: Model name (default: text-embedding-3-small)
            dimensions: Embedding dimensions (default: 1536)
            base_url: Optional custom base URL for OpenAI-compatible endpoints
        """
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate a single embedding."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def generate_embeddings(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts in a single API call."""
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dimensions,
        )
        # Return embeddings in the same order as input texts
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    async def close(self) -> None:
        await self._client.close()


class AzureOpenAIEmbeddingService(EmbeddingService):
    """Azure OpenAI embedding service."""

    DEFAULT_DIMENSIONS = 1536

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment_name: str,
        api_version: str = "2024-02-01",
        dimensions: int = DEFAULT_DIMENSIONS,
    ):
        """
        Initialize the Azure OpenAI embedding service.

        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint URL
            deployment_name: Name of the deployed embedding model
            api_version: API version to use
            dimensions: Embedding dimensions (default: 1536)
        """
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
        self._deployment_name = deployment_name
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate a single embedding."""
        response = await self._client.embeddings.create(
            model=self._deployment_name,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    async def generate_embeddings(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=self._deployment_name,
            input=texts,
            dimensions=self._dimensions,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    async def close(self) -> None:
        await self._client.close()


class GeminiEmbeddingService(EmbeddingService):
    """Google Gemini embedding service using the Google Generative AI SDK."""

    DEFAULT_MODEL = "gemini-embedding-001"
    DEFAULT_DIMENSIONS = 1024

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
    ):
        """
        Initialize the Gemini embedding service.

        Args:
            api_key: Google API key
            model: Model name (default: text-embedding-004)
            dimensions: Output embedding dimensions (default: 1024)
                       Note: Gemini models produce full embeddings (up to 3072 dimensions),
                       this parameter truncates to the requested size.
        """
        self._model = model
        self._dimensions = dimensions
        self._client = genai.Client(
            api_key=api_key if api_key else None
        )  # Use the configured genai module

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate a single embedding."""
        # Gemini API is synchronous, but we're in an async context
        # Run it in a thread pool to avoid blocking
        import asyncio

        def _sync_embed():
            result = self._client.models.embed_content(
                model=self._model,
                contents=[text],
                config=EmbedContentConfig(
                    output_dimensionality=self._dimensions,
                ),
            )
            return result.embeddings[0].values if result.embeddings else []

        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, _sync_embed)
        return embedding

    async def generate_embeddings(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        import asyncio

        def _sync_batch_embed():
            result = self._client.models.embed_content(
                model=self._model,
                contents=texts,
                config=EmbedContentConfig(
                    output_dimensionality=self._dimensions,
                ),
            )
            return (
                [embedding.values for embedding in result.embeddings]
                if result.embeddings
                else []
            )

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, _sync_batch_embed)
        return embeddings

    async def close(self) -> None:
        self._client.close()


def create_embedding_service(
    provider: EmbeddingProvider,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    dimensions: int = 1024,
    # OpenAI-specific
    openai_base_url: Optional[str] = None,
    # Azure-specific
    azure_endpoint: Optional[str] = None,
    azure_deployment_name: Optional[str] = None,
    azure_api_version: str = "2024-02-01",
) -> EmbeddingService:
    """
    Factory function to create the appropriate embedding service.

    Args:
        provider: The embedding provider to use
        api_key: API key for the provider
        model: Model name (for OpenAI or Gemini)
        dimensions: Embedding dimensions
        openai_base_url: Custom base URL for OpenAI-compatible endpoints
        azure_endpoint: Azure OpenAI endpoint URL
        azure_deployment_name: Azure OpenAI deployment name
        azure_api_version: Azure OpenAI API version

    Returns:
        Configured EmbeddingService instance
    """
    if provider == EmbeddingProvider.OPENAI:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        return OpenAIEmbeddingService(
            api_key=api_key,
            model=model or OpenAIEmbeddingService.DEFAULT_MODEL,
            dimensions=dimensions,
            base_url=openai_base_url,
        )

    elif provider == EmbeddingProvider.AZURE_OPENAI:
        if not api_key:
            raise ValueError("Azure OpenAI API key is required")
        if not azure_endpoint:
            raise ValueError("Azure OpenAI endpoint is required")
        if not azure_deployment_name:
            raise ValueError("Azure OpenAI deployment name is required")
        return AzureOpenAIEmbeddingService(
            api_key=api_key,
            endpoint=azure_endpoint,
            deployment_name=azure_deployment_name,
            api_version=azure_api_version,
            dimensions=dimensions,
        )

    elif provider == EmbeddingProvider.GEMINI:
        if not api_key:
            raise ValueError("Google API key is required")
        return GeminiEmbeddingService(
            api_key=api_key,
            model=model or GeminiEmbeddingService.DEFAULT_MODEL,
            dimensions=dimensions,
        )

    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


# Global embedding service instance (set during initialization)
_embedding_service: Optional[EmbeddingService] = None


def set_embedding_service(service: EmbeddingService) -> None:
    """Set the global embedding service instance."""
    global _embedding_service
    _embedding_service = service


def get_embedding_service() -> EmbeddingService:
    """Get the global embedding service instance."""
    if _embedding_service is None:
        raise RuntimeError(
            "Embedding service not initialized. "
            "Please configure embedding settings in environment variables."
        )
    return _embedding_service


def is_embedding_service_configured() -> bool:
    """Check if an embedding service is configured."""
    return _embedding_service is not None
