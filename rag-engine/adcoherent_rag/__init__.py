"""AdCoherent Labs — regulatory RAG engine (Layer 3 ingestion + retrieval).

Pipeline: manifest -> fetch -> raw snapshot (sha256) -> normalize (canonical
section units) -> structure-aware chunking -> local embeddings (MiniLM) ->
pgvector + tsvector hybrid RRF retrieval, with effective-dated versioned
storage (never update-in-place).
"""

__version__ = "0.1.0"
