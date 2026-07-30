from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from ..contracts import ErrorCode
from ..errors import ApplicationError
from ..matching.embedding_text import MAX_EMBEDDING_TOKENS, truncate_embedding_text

EMBEDDING_DIMENSION = 512


class LocalBGEEmbedding:
    """Lazy, local-only BGE embedding adapter.

    LangChain's implementation is synchronous, so all model work is moved to
    a worker thread.  The model is loaded once per adapter process and calls
    are serialized because Sentence Transformers model instances are not
    assumed to be safe for concurrent mutation.
    """

    dimension = EMBEDDING_DIMENSION
    _model_cache: ClassVar[dict[tuple[str, str | None], Any]] = {}
    _model_cache_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        model_path: str | None,
        *,
        model_revision: str | None = None,
        query_timeout_seconds: float = 5.0,
        batch_timeout_seconds: float = 60.0,
    ) -> None:
        self._model_path = model_path
        self._model_revision = model_revision
        self._query_timeout_seconds = query_timeout_seconds
        self._batch_timeout_seconds = batch_timeout_seconds
        self._model: Any | None = None
        self._model_lock = threading.RLock()

    async def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise self._dependency_error("embedding query must not be empty")
        result = await self._run_with_timeout(
            lambda: self._embed_sync("embed_query", [text])[0],
            self._query_timeout_seconds,
        )
        return self._validate_vector(result)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise self._dependency_error("embedding documents must not contain empty text")
        result = await self._run_with_timeout(
            lambda: self._embed_sync("embed_documents", list(texts)),
            self._batch_timeout_seconds,
        )
        if not isinstance(result, list) or len(result) != len(texts):
            raise self._dependency_error("embedding provider returned an invalid batch length")
        return [self._validate_vector(vector) for vector in result]

    async def _run_with_timeout(self, operation: Any, timeout: float) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(operation), timeout=timeout)
        except TimeoutError as exc:
            raise self._dependency_error("local embedding call timed out") from exc
        except ApplicationError:
            raise
        except Exception as exc:
            raise self._dependency_error("local embedding dependency failed") from exc

    def _embed_sync(self, method: str, texts: list[str]) -> Any:
        model = self._get_model()
        texts = [self._truncate_for_model(model, text) for text in texts]
        with self._model_lock:
            if method == "embed_query":
                return [model.embed_query(texts[0])]
            return model.embed_documents(texts)

    @staticmethod
    def _truncate_for_model(model: Any, text: str) -> str:
        tokenizer = getattr(getattr(model, "client", None), "tokenizer", None)
        if tokenizer is None:
            return truncate_embedding_text(text)
        try:
            token_ids = tokenizer.encode(
                text,
                add_special_tokens=True,
                truncation=False,
            )
            if len(token_ids) <= MAX_EMBEDDING_TOKENS:
                return text
            return tokenizer.decode(token_ids[:MAX_EMBEDDING_TOKENS], skip_special_tokens=True)
        except Exception as exc:
            raise LocalBGEEmbedding._dependency_error("local embedding tokenizer failed") from exc

    def _get_model(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            model_path = self._resolve_model_path()
            cache_key = (str(model_path), self._model_revision)
            with self._model_cache_lock:
                cached = self._model_cache.get(cache_key)
                if cached is not None:
                    self._model = cached
                    return cached
            try:
                from importlib import import_module

                HuggingFaceEmbeddings = import_module("langchain_huggingface").HuggingFaceEmbeddings

                model_kwargs: dict[str, Any] = {
                    "device": "cpu",
                    "local_files_only": True,
                }
                if self._model_revision:
                    model_kwargs["revision"] = self._model_revision
                self._model = HuggingFaceEmbeddings(
                    model_name=str(model_path),
                    model_kwargs=model_kwargs,
                    encode_kwargs={"normalize_embeddings": True},
                )
                with self._model_cache_lock:
                    self._model_cache[cache_key] = self._model
            except ApplicationError:
                raise
            except Exception as exc:
                raise self._dependency_error("local embedding model could not be loaded") from exc
            return self._model

    def _resolve_model_path(self) -> Path:
        if not self._model_path:
            raise self._dependency_error(
                "embedding model path is not configured; set JOBPICKY_EMBEDDING_MODEL_PATH"
            )
        path = Path(self._model_path).expanduser()
        if not path.is_dir():
            raise self._dependency_error("configured embedding model path does not exist")
        if (path / "config.json").is_file():
            return path

        snapshots = path / "snapshots"
        if self._model_revision:
            revision_path = snapshots / self._model_revision
            if (revision_path / "config.json").is_file():
                return revision_path
        candidates = (
            sorted(candidate for candidate in snapshots.iterdir() if candidate.is_dir())
            if snapshots.is_dir()
            else []
        )
        if len(candidates) == 1 and (candidates[0] / "config.json").is_file():
            return candidates[0]
        if not candidates:
            raise self._dependency_error("embedding model snapshot was not found")
        raise self._dependency_error("embedding model path must resolve to one local snapshot")

    @staticmethod
    def _validate_vector(vector: Any) -> list[float]:
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise LocalBGEEmbedding._dependency_error(
                "embedding provider returned a non-numeric vector"
            ) from exc
        if len(values) != EMBEDDING_DIMENSION:
            raise LocalBGEEmbedding._dependency_error(
                "embedding provider returned dimension "
                f"{len(values)}, expected {EMBEDDING_DIMENSION}"
            )
        return values

    @staticmethod
    def _dependency_error(message: str) -> ApplicationError:
        return ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            message,
            status_code=503,
            details={"dependency": "embedding"},
        )


LocalHuggingFaceEmbeddings = LocalBGEEmbedding


__all__ = [
    "EMBEDDING_DIMENSION",
    "LocalBGEEmbedding",
    "LocalHuggingFaceEmbeddings",
]
