"""Embedding client for LM Studio (OpenAI-compatible API)."""

import logging
import struct
import time
from typing import List, Optional

import requests

from asky.config import (
    RESEARCH_EMBEDDING_API_URL,
    RESEARCH_EMBEDDING_MODEL,
    RESEARCH_EMBEDDING_TIMEOUT,
    RESEARCH_EMBEDDING_BATCH_SIZE,
    RESEARCH_EMBEDDING_RETRY_ATTEMPTS,
    RESEARCH_EMBEDDING_RETRY_BACKOFF_SECONDS,
)

logger = logging.getLogger(__name__)
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


class EmbeddingClient:
    """Client for local embedding API (LM Studio / OpenAI-compatible)."""

    _instance: Optional["EmbeddingClient"] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for efficient reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_url: str = None,
        model: str = None,
        timeout: int = None,
        batch_size: int = None,
        retry_attempts: int = None,
        retry_backoff_seconds: float = None,
    ):
        # Skip re-initialization for singleton
        if self._initialized:
            return

        self.api_url = api_url or RESEARCH_EMBEDDING_API_URL
        self.model = model or RESEARCH_EMBEDDING_MODEL
        self.timeout = timeout or RESEARCH_EMBEDDING_TIMEOUT
        self.batch_size = batch_size or RESEARCH_EMBEDDING_BATCH_SIZE
        self.retry_attempts = retry_attempts or RESEARCH_EMBEDDING_RETRY_ATTEMPTS
        self.retry_backoff_seconds = (
            retry_backoff_seconds or RESEARCH_EMBEDDING_RETRY_BACKOFF_SECONDS
        )
        self._session = requests.Session()

        # Usage tracking
        self.texts_embedded: int = 0
        self.api_calls: int = 0
        self.prompt_tokens: int = 0

        self._initialized = True

        logger.debug(
            f"EmbeddingClient initialized: url={self.api_url}, model={self.model}"
        )

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Automatically batches requests if needed.
        """
        if not texts:
            return []

        # Filter out empty texts
        texts = [t for t in texts if t and t.strip()]
        if not texts:
            return []

        all_embeddings = []

        # Process in batches
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a single batch."""
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self._session.post(
                    self.api_url,
                    json={"input": texts, "model": self.model},
                    timeout=self.timeout,
                )
                response.raise_for_status()

                data = response.json()

                # Track usage
                self.api_calls += 1
                self.texts_embedded += len(texts)
                usage = data.get("usage", {})
                self.prompt_tokens += usage.get("prompt_tokens", 0)

                # Handle different response formats
                if "data" in data:
                    # OpenAI format
                    return [item["embedding"] for item in data["data"]]
                if "embeddings" in data:
                    # Alternative format
                    return data["embeddings"]
                raise ValueError(f"Unexpected response format: {list(data.keys())}")
            except requests.exceptions.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response is not None else None
                is_retryable = status_code in RETRYABLE_HTTP_STATUS_CODES
                if is_retryable and attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                logger.error(f"Embedding API HTTP error: status={status_code}")
                raise
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                if attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                if isinstance(e, requests.exceptions.ConnectionError):
                    logger.error(
                        f"Failed to connect to embedding API at {self.api_url}. "
                        "Is LM Studio running with an embedding model loaded?"
                    )
                else:
                    logger.error(
                        f"Embedding API request timed out after {self.timeout}s"
                    )
                raise
            except Exception as e:
                logger.error(f"Embedding API error: {e}")
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Embedding API request failed unexpectedly")

    def _sleep_before_retry(self, attempt: int) -> None:
        """Sleep with linear backoff before retrying transient errors."""
        delay_seconds = self.retry_backoff_seconds * attempt
        time.sleep(delay_seconds)

    def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        result = self.embed([text])
        return result[0] if result else []

    def is_available(self) -> bool:
        """Check if the embedding API is available."""
        try:
            # Try a simple embedding request
            self.embed_single("test")
            return True
        except Exception:
            return False

    @staticmethod
    def serialize_embedding(embedding: List[float]) -> bytes:
        """Convert embedding to bytes for SQLite storage.

        Uses float32 format (4 bytes per float).
        """
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def deserialize_embedding(data: bytes) -> List[float]:
        """Convert bytes back to embedding list."""
        if not data:
            return []
        count = len(data) // 4  # 4 bytes per float32
        return list(struct.unpack(f"{count}f", data))

    def get_usage_stats(self) -> dict:
        """Get current usage statistics."""
        return {
            "texts_embedded": self.texts_embedded,
            "api_calls": self.api_calls,
            "prompt_tokens": self.prompt_tokens,
        }


def get_embedding_client() -> EmbeddingClient:
    """Get the singleton embedding client instance."""
    return EmbeddingClient()
