"""Embedding client backed by sentence-transformers."""

import contextlib
import io
import logging
import os
import struct
from typing import Any, List, Optional

from asky.config import (
    RESEARCH_EMBEDDING_BATCH_SIZE,
    RESEARCH_EMBEDDING_DEVICE,
    RESEARCH_EMBEDDING_LOCAL_FILES_ONLY,
    RESEARCH_EMBEDDING_MODEL,
    RESEARCH_EMBEDDING_NORMALIZE,
)

logger = logging.getLogger(__name__)
UNBOUNDED_TOKENIZER_LIMIT = 100_000
FALLBACK_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment]


class EmbeddingClient:
    """Singleton sentence-transformers client used across research tools."""

    _instance: Optional["EmbeddingClient"] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for efficient reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_url: str = None,  # Backward-compatible no-op
        model: str = None,
        timeout: int = None,  # Backward-compatible no-op
        batch_size: int = None,
        retry_attempts: int = None,  # Backward-compatible no-op
        retry_backoff_seconds: float = None,  # Backward-compatible no-op
        device: str = None,
        normalize_embeddings: Optional[bool] = None,
        local_files_only: Optional[bool] = None,
    ):
        if self._initialized:
            return

        self.api_url = api_url
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

        self.model = model or RESEARCH_EMBEDDING_MODEL
        self.batch_size = batch_size or RESEARCH_EMBEDDING_BATCH_SIZE
        self.device = device or RESEARCH_EMBEDDING_DEVICE
        self.normalize_embeddings = (
            RESEARCH_EMBEDDING_NORMALIZE
            if normalize_embeddings is None
            else bool(normalize_embeddings)
        )
        self.local_files_only = (
            RESEARCH_EMBEDDING_LOCAL_FILES_ONLY
            if local_files_only is None
            else bool(local_files_only)
        )

        self._model: Optional[Any] = None
        self._tokenizer: Optional[Any] = None
        self._model_load_error: Optional[Exception] = None

        # Usage tracking
        self.texts_embedded: int = 0
        self.api_calls: int = 0
        self.prompt_tokens: int = 0

        self._initialized = True
        logger.debug(
            "EmbeddingClient initialized: model=%s, device=%s",
            self.model,
            self.device,
        )

    def _load_sentence_transformer(
        self, model_name: str, local_files_only: bool
    ) -> Any:
        """Load a sentence-transformer model with compatibility fallback."""
        kwargs = {"device": self.device}
        if local_files_only:
            kwargs["local_files_only"] = True
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()

        def _construct_model(active_kwargs: dict) -> Any:
            with _silence_process_output(captured_stdout, captured_stderr):
                return SentenceTransformer(model_name, **active_kwargs)

        try:
            return _construct_model(kwargs)
        except TypeError:
            kwargs.pop("local_files_only", None)
            return _construct_model(kwargs)

    def _load_model_with_cache_preference(self, model_name: str) -> Any:
        """Load from local cache first, then allow network download if configured."""
        try:
            model = self._load_sentence_transformer(
                model_name=model_name,
                local_files_only=True,
            )
            logger.debug(
                "Loaded embedding model '%s' from local Hugging Face cache.",
                model_name,
            )
            return model
        except Exception as local_exc:
            if self.local_files_only:
                raise local_exc
            logger.debug(
                "Embedding model '%s' not available locally, attempting remote load.",
                model_name,
            )
            return self._load_sentence_transformer(
                model_name=model_name,
                local_files_only=False,
            )

    def _ensure_model_loaded(self) -> Any:
        """Load sentence-transformer lazily and cache it."""
        if self._model is not None:
            return self._model
        if self._model_load_error is not None:
            raise RuntimeError("Embedding model is unavailable") from self._model_load_error

        if SentenceTransformer is None:
            self._model_load_error = RuntimeError(
                "sentence-transformers is required for research embeddings. "
                "Install dependencies and retry."
            )
            raise RuntimeError("Embedding model is unavailable") from self._model_load_error

        configured_model = self.model
        try:
            self._model = self._load_model_with_cache_preference(
                model_name=configured_model,
            )
        except Exception as primary_exc:
            should_try_fallback = (
                not self.local_files_only and configured_model != FALLBACK_EMBEDDING_MODEL
            )
            if should_try_fallback:
                logger.warning(
                    "Failed to load embedding model '%s'. "
                    "Falling back to '%s' with Hugging Face auto-download enabled.",
                    configured_model,
                    FALLBACK_EMBEDDING_MODEL,
                )
                try:
                    self._model = self._load_model_with_cache_preference(
                        model_name=FALLBACK_EMBEDDING_MODEL,
                    )
                    self.model = FALLBACK_EMBEDDING_MODEL
                    logger.info(
                        "Loaded fallback embedding model '%s' successfully. "
                        "Update research.embedding.model to avoid repeated primary model load failures.",
                        self.model,
                    )
                except Exception as fallback_exc:
                    self._model_load_error = fallback_exc
                    logger.error(
                        "Failed to load sentence-transformer model '%s': %s",
                        configured_model,
                        primary_exc,
                    )
                    logger.error(
                        "Fallback embedding model '%s' also failed: %s",
                        FALLBACK_EMBEDDING_MODEL,
                        fallback_exc,
                    )
                    raise RuntimeError("Embedding model is unavailable") from fallback_exc
            else:
                self._model_load_error = primary_exc
                logger.error(
                    "Failed to load sentence-transformer model '%s': %s",
                    configured_model,
                    primary_exc,
                )
                raise RuntimeError("Embedding model is unavailable") from primary_exc

        self._tokenizer = getattr(self._model, "tokenizer", None)
        return self._model

    def _to_embedding_rows(self, encoded: Any) -> List[List[float]]:
        """Normalize model output to List[List[float]]."""
        rows = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        if rows is None:
            return []
        if isinstance(rows, tuple):
            rows = list(rows)
        if not isinstance(rows, list):
            return []
        if rows and isinstance(rows[0], (int, float)):
            rows = [rows]
        normalized: List[List[float]] = []
        for row in rows:
            if not isinstance(row, list):
                continue
            normalized.append([float(value) for value in row])
        return normalized

    def _count_text_tokens(self, texts: List[str]) -> int:
        """Estimate total input tokens for lightweight usage tracking."""
        tokenizer = self.get_tokenizer()
        if tokenizer is None:
            return 0
        max_length = self.max_seq_length

        total = 0
        for text in texts:
            try:
                kwargs = {"add_special_tokens": False}
                if max_length > 0:
                    kwargs["truncation"] = True
                    kwargs["max_length"] = max_length
                token_ids = tokenizer.encode(text, **kwargs)
            except TypeError:
                token_ids = tokenizer.encode(text)
            except Exception:
                continue
            total += len(token_ids)
        return total

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode one text batch using sentence-transformers."""
        model = self._ensure_model_loaded()
        encoded = model.encode(
            texts,
            batch_size=len(texts),
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=self.normalize_embeddings,
        )
        rows = self._to_embedding_rows(encoded)

        self.api_calls += 1
        self.texts_embedded += len(texts)
        self.prompt_tokens += self._count_text_tokens(texts)
        return rows

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        filtered_texts = [text for text in texts if text and text.strip()]
        if not filtered_texts:
            return []

        all_embeddings: List[List[float]] = []
        for i in range(0, len(filtered_texts), self.batch_size):
            batch = filtered_texts[i : i + self.batch_size]
            all_embeddings.extend(self._embed_batch(batch))
        return all_embeddings

    def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        result = self.embed([text])
        return result[0] if result else []

    def is_available(self) -> bool:
        """Check whether the embedding model is loadable."""
        try:
            self._ensure_model_loaded()
            return True
        except Exception:
            return False

    def has_model_load_failure(self) -> bool:
        """Return True if a model load failure has already been cached."""
        return self._model is None and self._model_load_error is not None

    def get_tokenizer(self) -> Optional[Any]:
        """Expose tokenizer for token-aware chunking."""
        try:
            self._ensure_model_loaded()
        except Exception:
            return None
        return self._tokenizer

    @property
    def max_seq_length(self) -> int:
        """Expose finite model sequence length when available."""
        try:
            model = self._ensure_model_loaded()
        except Exception:
            return 0
        raw_value = getattr(model, "max_seq_length", 0)
        try:
            max_length = int(raw_value)
        except (TypeError, ValueError):
            return 0
        if max_length <= 0 or max_length >= UNBOUNDED_TOKENIZER_LIMIT:
            return 0
        return max_length

    @staticmethod
    def serialize_embedding(embedding: List[float]) -> bytes:
        """Convert embedding to bytes for SQLite storage."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def deserialize_embedding(data: bytes) -> List[float]:
        """Convert bytes back to embedding list."""
        if not data:
            return []
        count = len(data) // 4
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


@contextlib.contextmanager
def _silence_process_output(
    captured_stdout: io.StringIO, captured_stderr: io.StringIO
):
    """Silence Python-level and native fd stdout/stderr during noisy model loads."""
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
            captured_stderr
        ):
            yield
    finally:
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)
        os.close(devnull_fd)
