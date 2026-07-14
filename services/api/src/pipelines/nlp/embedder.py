import os, time, numpy as np
from typing import List
_OPENAI = os.getenv("OPENAI_API_KEY","").strip() != ""
if _OPENAI:
    from openai import OpenAI; _client = OpenAI(); _model = os.getenv("OPENAI_EMBED_MODEL","text-embedding-3-small")
else:
    from sentence_transformers import SentenceTransformer; _st = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


class EmbeddingUnavailableError(RuntimeError):
    def __init__(self, message: str, *, model: str = "", error_type: str = "") -> None:
        super().__init__(message)
        self.model = model
        self.error_type = error_type or self.__class__.__name__


def embedding_model_name() -> str:
    return _model if _OPENAI else "sentence-transformers/all-MiniLM-L6-v2"


def _is_retryable_embedding_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if "rate_limit" in text or "temporarily" in text or "timeout" in text:
        return True
    return "model_not_found" in text and type(exc).__name__ in {
        "PermissionDeniedError",
        "NotFoundError",
    }


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts: return np.zeros((0,384),dtype=np.float32)
    if _OPENAI:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                out = _client.embeddings.create(input=texts, model=_model)
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 2 or not _is_retryable_embedding_error(exc):
                    raise EmbeddingUnavailableError(
                        str(exc),
                        model=_model,
                        error_type=type(exc).__name__,
                    ) from exc
                time.sleep(0.5 * (attempt + 1))
        else:
            raise EmbeddingUnavailableError(
                str(last_exc or "Embedding request failed"),
                model=_model,
                error_type=type(last_exc).__name__ if last_exc else "EmbeddingError",
            )
        vecs = [np.array(d.embedding, dtype=np.float32) for d in out.data]
        return np.vstack(vecs)
    arr = _st.encode(texts, normalize_embeddings=True)
    return np.array(arr, dtype=np.float32)
