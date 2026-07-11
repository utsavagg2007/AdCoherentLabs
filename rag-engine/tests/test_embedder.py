"""FakeEmbedder determinism + get_embedder() selection under EMBEDDING_FAKE."""

import math

from adcoherent_rag import config
from adcoherent_rag.embed.embedder import FakeEmbedder, get_embedder


def test_get_embedder_returns_fake_under_env():
    embedder = get_embedder()
    assert isinstance(embedder, FakeEmbedder)
    assert embedder.model_name == "fake"


def test_dimensions_and_unit_norm():
    embedder = FakeEmbedder()
    (vec,) = embedder.encode(["APY advertising disclosure requirements"])
    assert len(vec) == config.EMBEDDING_DIM == embedder.dim
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6


def test_determinism_and_distinctness():
    embedder = FakeEmbedder()
    a1, b, a2 = embedder.encode(["text a", "text b", "text a"])
    assert a1 == a2
    assert a1 != b


def test_empty_input():
    assert FakeEmbedder().encode([]) == []
