"""Frozen sentence embeddings for framework-routing and claim-recall support.

Wraps a pretrained HuggingFace sentence-transformer used strictly as-is:
no fine-tuning, no training, inference against fixed weights only. Given
the same model revision the outputs are reproducible, so the exact
name+revision is exposed via ``get_embedding_model_version()`` for the
``schema.Provenance.embedding_model_version`` audit field.

Scope guard: embeddings *support* routing and recall. Entity/number
extraction (APR, fees, rates, amounts) stays 100% deterministic
rule-based in ``nlp.entities`` and must never route through this module.
"""

from __future__ import annotations

import functools
import os

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# MiniLM-L6 truncates at 256 word-pieces; encoding a whole long asset
# would silently score only an arbitrary prefix. Callers (routing) cap
# their input to roughly this many characters before comparing.
MAX_INPUT_CHARS = 1000

_model = None  # loaded once, reused for every call


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME, device="cpu")
        _model.eval()  # frozen: inference only, never trained here
    return _model


@functools.lru_cache(maxsize=512)
def _unit_vector(text: str):
    """L2-normalized embedding for one text, memoized.

    The fallbacks compare each segment against a small fixed set of
    reference sentences, so caching per-text unit vectors means every
    reference is encoded exactly once (ever) and each distinct segment
    exactly once — instead of re-encoding both sides on every pairwise
    call. Vectors are treated as read-only.
    """
    return _get_model().encode(text, convert_to_numpy=True,
                               normalize_embeddings=True)


def embed_text(text: str) -> list[float]:
    """Embedding vector for one text (384 floats for MiniLM-L6)."""
    return _unit_vector(text).tolist()


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity of the two texts' embeddings, in [-1, 1].

    Both operands are cached unit vectors (see :func:`_unit_vector`), so
    repeated comparisons against the same reference sentences reuse a
    single encode.
    """
    return float(_unit_vector(text_a) @ _unit_vector(text_b))


def get_embedding_model_version() -> str:
    """Exact model name+revision for provenance.

    'name@<commit>' when the HF cache can resolve the downloaded
    snapshot's commit hash; bare model name as a fallback so provenance
    is never empty.
    """
    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download(MODEL_NAME, local_files_only=True)
        return f"{MODEL_NAME}@{os.path.basename(path)}"
    except Exception:
        return MODEL_NAME


if __name__ == "__main__":
    credit = "Get a low 5.99% APR on your new credit card today."
    credit_para = "Our credit card offers an annual percentage rate as low as 5.99%."
    invest = "Our portfolio delivered strong investment returns last year."
    weather = "It rained heavily in Seattle all weekend."

    print(f"model: {get_embedding_model_version()}")
    print(f"embedding dim: {len(embed_text(credit))}\n")

    pairs = [
        ("credit vs credit-paraphrase", credit, credit_para),
        ("credit vs investment      ", credit, invest),
        ("credit vs weather         ", credit, weather),
        ("investment vs weather     ", invest, weather),
    ]
    sims = {}
    for name, a, b in pairs:
        sims[name.strip()] = s = semantic_similarity(a, b)
        print(f"{name}  {s:.3f}")

    # Sanity ordering: paraphrase > related finance topics > unrelated.
    assert sims["credit vs credit-paraphrase"] > sims["credit vs investment"], \
        "paraphrase should outscore cross-topic"
    assert sims["credit vs investment"] > sims["credit vs weather"], \
        "finance topics should outscore finance-vs-weather"
    print("\nsanity ordering holds: paraphrase > cross-topic > unrelated")
