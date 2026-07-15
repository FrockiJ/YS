from __future__ import annotations

import os
import time
from typing import Any, List, Optional

import numpy as np


EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower() or "local"
EMBEDDING_MODEL = (
    os.getenv("EMBEDDING_MODEL", "").strip()
    or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

_local_model: Optional[Any] = None
_openai_client: Optional[Any] = None


class EmbeddingUnavailableError(RuntimeError):
    def __init__(self, message: str, *, model: str = "", error_type: str = "") -> None:
        super().__init__(message)
        self.model = model
        self.error_type = error_type or self.__class__.__name__


def embedding_model_name() -> str:
    return EMBEDDING_MODEL


def embedding_dimension() -> int:
    return EMBEDDING_DIM


def embedding_provider_name() -> str:
    return EMBEDDING_PROVIDER


def _get_local_model():
    global _local_model
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _local_model = SentenceTransformer(EMBEDDING_MODEL)
        except Exception as exc:
            raise EmbeddingUnavailableError(
                str(exc),
                model=EMBEDDING_MODEL,
                error_type=type(exc).__name__,
            ) from exc
    return _local_model


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            raise EmbeddingUnavailableError(
                "OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai",
                model=EMBEDDING_MODEL,
                error_type="MissingConfiguration",
            )
        try:
            from openai import OpenAI

            _openai_client = OpenAI()
        except Exception as exc:
            raise EmbeddingUnavailableError(
                str(exc),
                model=EMBEDDING_MODEL,
                error_type=type(exc).__name__,
            ) from exc
    return _openai_client


def _validate_dimensions(array: np.ndarray) -> np.ndarray:
    if array.ndim != 2 or array.shape[1] != EMBEDDING_DIM:
        actual = array.shape[1] if array.ndim == 2 and array.shape else 0
        raise EmbeddingUnavailableError(
            f"Embedding dimension mismatch: configured={EMBEDDING_DIM}, actual={actual}. Rebuild the RAG index after changing models.",
            model=EMBEDDING_MODEL,
            error_type="EmbeddingDimensionMismatch",
        )
    return array.astype(np.float32, copy=False)


def _is_retryable_embedding_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if "rate_limit" in text or "temporarily" in text or "timeout" in text:
        return True
    return "model_not_found" in text and type(exc).__name__ in {"PermissionDeniedError", "NotFoundError"}


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if EMBEDDING_PROVIDER == "local":
        try:
            array = np.asarray(_get_local_model().encode(texts, normalize_embeddings=True), dtype=np.float32)
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError(
                str(exc),
                model=EMBEDDING_MODEL,
                error_type=type(exc).__name__,
            ) from exc
        return _validate_dimensions(array)
    if EMBEDDING_PROVIDER == "openai":
        client = _get_openai_client()
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = client.embeddings.create(
                    input=texts,
                    model=EMBEDDING_MODEL,
                    dimensions=EMBEDDING_DIM,
                )
                array = np.vstack([np.asarray(item.embedding, dtype=np.float32) for item in response.data])
                return _validate_dimensions(array)
            except Exception as exc:
                last_exc = exc
                if attempt >= 2 or not _is_retryable_embedding_error(exc):
                    break
                time.sleep(0.5 * (attempt + 1))
        raise EmbeddingUnavailableError(
            str(last_exc or "Embedding request failed"),
            model=EMBEDDING_MODEL,
            error_type=type(last_exc).__name__ if last_exc else "EmbeddingError",
        ) from last_exc
    raise EmbeddingUnavailableError(
        f"Unsupported EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}",
        model=EMBEDDING_MODEL,
        error_type="InvalidConfiguration",
    )
