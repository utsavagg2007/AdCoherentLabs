"""Embedding backends.

`SentenceTransformerEmbedder` is the real backend (lazy-imports
sentence_transformers so the test suite never needs the dependency or the
model download). `FakeEmbedder` is a deterministic stand-in used when
``EMBEDDING_FAKE=1`` — same text always maps to the same unit vector, which
is enough for tests and offline pipeline dry-runs.

The chunk rows record ``model_name``/``dim`` so swapping models later is a
lazy re-embed, not a schema migration.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
from typing import Any

from .. import config

logger = logging.getLogger(__name__)


class BaseEmbedder:
    """Common interface: `encode` maps texts to plain-python float vectors."""

    model_name: str
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class SentenceTransformerEmbedder(BaseEmbedder):
    """sentence-transformers backend (model loaded lazily, once)."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or config.EMBEDDING_MODEL_NAME
        self.dim = config.EMBEDDING_DIM
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # lazy heavy import
            except ImportError as e:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "sentence-transformers is not installed; install it or set "
                    "EMBEDDING_FAKE=1 to use the deterministic fake embedder"
                ) from e
            logger.info("loading embedding model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            model_dim = self._model.get_sentence_embedding_dimension()
            if model_dim and model_dim != self.dim:
                logger.warning(
                    "embedding model %s produces %d-dim vectors but "
                    "config.EMBEDDING_DIM is %d; using the model's dimension",
                    self.model_name,
                    model_dim,
                    self.dim,
                )
                self.dim = model_dim
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(
            texts,
            batch_size=config.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in vec] for vec in vectors]


class FakeEmbedder(BaseEmbedder):
    """Deterministic hash-seeded embedder for tests and offline runs."""

    model_name = "fake"

    def __init__(self) -> None:
        self.dim = config.EMBEDDING_DIM

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        rng = random.Random(seed)
        vec = [rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:  # pragma: no cover - astronomically unlikely
            vec[0] = 1.0
            norm = 1.0
        return [x / norm for x in vec]


def get_embedder() -> BaseEmbedder:
    """FakeEmbedder under EMBEDDING_FAKE=1, real model otherwise."""
    if config.EMBEDDING_FAKE:
        logger.info("EMBEDDING_FAKE=1 — using FakeEmbedder")
        return FakeEmbedder()
    return SentenceTransformerEmbedder()
