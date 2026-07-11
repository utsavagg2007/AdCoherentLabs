"""Central configuration. Everything reads from environment / .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # rag-engine/
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_manifest_path() -> Path:
    env = os.environ.get("MANIFEST_PATH")
    if env:
        return Path(env)
    candidates = [
        PROJECT_ROOT / "adcoherent_regulatory_sources.json",
        PROJECT_ROOT.parent / "adcoherent_regulatory_sources.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


DATABASE_URL = os.environ.get("DATABASE_URL", "")
MANIFEST_PATH = _resolve_manifest_path()
RAW_STORAGE_DIR = Path(os.environ.get("RAW_STORAGE_DIR", PROJECT_ROOT / "data" / "raw"))

# Manual snapshots — sources with no plain-HTTP scrape path (manual_stub
# family) are ingested from files saved by hand into
# data/manual/<source-id>/*.html|.pdf|.txt instead of being skipped.
MANUAL_SNAPSHOT_DIR = Path(
    os.environ.get("MANUAL_SNAPSHOT_DIR", PROJECT_ROOT / "data" / "manual")
)

# Embeddings — model name and dim are recorded on every chunk row so a future
# model swap is a lazy re-embed, not a migration.
EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "384"))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "64"))
EMBEDDING_FAKE = os.environ.get("EMBEDDING_FAKE", "") == "1"

# Chunking — MiniLM-L6-v2 truncates around 256 wordpiece tokens (~1000 chars),
# so chunks are kept small enough that the embedded text is not cut off.
CHUNK_TARGET_CHARS = 900
CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150

# HTTP (env-tunable: verification sweeps drop these so geo-blocked state
# hosts fail fast instead of burning minutes in retries)
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "60"))            # read timeout
HTTP_CONNECT_TIMEOUT = int(os.environ.get("HTTP_CONNECT_TIMEOUT", "15"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "3"))
HTTP_BACKOFF_SECONDS = 2.0
HTTP_USER_AGENT = (
    "AdCoherentLabs-RAG/0.1 (regulatory compliance research; "
    "contact: god.utsav200@gmail.com)"
)

# Ingest coverage — tier-1 federal plus these priority states (per manifest notes).
PRIORITY_STATE_JURISDICTIONS = {
    "US-CA", "US-NY", "US-TX", "US-FL", "US-IL", "US-MA", "US-NJ",
}

# Hybrid retrieval
RRF_K = 60                 # reciprocal-rank-fusion constant
RETRIEVAL_CANDIDATES = 50  # candidates fetched per arm before fusion
