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

import os

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None  # loaded once, reused for every call


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME, device="cpu")
        _model.eval()  # frozen: inference only, never trained here
    return _model


def embed_text(text: str) -> list[float]:
    """Embedding vector for one text (384 floats for MiniLM-L6)."""
    vec = _get_model().encode(text, convert_to_numpy=True)
    return vec.tolist()


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity of the two texts' embeddings, in [-1, 1]."""
    embs = _get_model().encode(
        [text_a, text_b], convert_to_numpy=True, normalize_embeddings=True
    )
    return float(embs[0] @ embs[1])


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
