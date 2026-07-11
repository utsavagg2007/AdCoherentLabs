# Implementation guide — AdCoherent RAG engine

Read these contract files FIRST (they already exist and must not be modified):

- `adcoherent_rag/models.py` — dataclasses (SourceSpec, FetchResult, Paragraph, SectionUnit, Chunk, RetrievalResult)
- `adcoherent_rag/config.py` — configuration constants
- `adcoherent_rag/manifest.py` — manifest loading, `frameworks_for`, `source_family`, `parse_cfr_citation`, `default_ingest_sources`, `MANUAL_STUB_SOURCES`
- `adcoherent_rag/fetch/base.py` — `Fetcher` protocol + `FetchError`
- `adcoherent_rag/fetch/http.py` — `get(url, ...)` and `fetch_url(source_id, url, *, kind, extra_meta, headers)` helpers
- `adcoherent_rag/normalize/base.py` — `Normalizer` protocol + `NormalizeError`
- `adcoherent_rag/store/schema.sql` — the full DDL (do not change it)
- `../adcoherent_regulatory_sources.json` — the source manifest (one level above rag-engine/)

General rules for every module:

- Python 3.11+ style, `from __future__ import annotations`, type hints everywhere.
- Raise `FetchError` / `NormalizeError` — never let bare exceptions escape a fetcher/normalizer.
- No prints; use `logging.getLogger(__name__)`.
- Only stdlib + requirements.txt deps (requests, bs4, lxml, PyMuPDF as `fitz`, sentence-transformers, psycopg 3, pgvector, dotenv).
- Heavy imports (sentence_transformers, fitz) must be lazy (inside function/method) so the test suite runs without them.
- Verify your files with `python3 -m py_compile <file>` before finishing.
- Write ONLY your assigned files. Do not create or edit any others.

Exact module assignments and public interfaces follow. Class/function names are contracts — `pipeline.py` and the tests import them by these exact names.

---

## M1 — eCFR family: `adcoherent_rag/fetch/ecfr.py` + `adcoherent_rag/normalize/ecfr_xml.py`

`fetch/ecfr.py`:

```python
class EcfrFetcher:
    def fetch(self, spec: SourceSpec) -> list[FetchResult]: ...
```

Behavior:
1. `title, part, section = parse_cfr_citation(spec.citation)`.
2. Resolve the latest point-in-time date: GET `https://www.ecfr.gov/api/versioner/v1/titles.json`, find this title's `up_to_date_as_of` (fallback: today's date).
3. GET full XML: `https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}` (append `&section={part}.{section}` when the citation is section-scoped — check the API's expected `section` format and use what works; if a section-scoped request 404s, fall back to the whole part).
4. GET the per-section amendment dates: `https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?issue_date%5Blte%5D={date}` filtered to the part (or the part-scoped variant if supported). Build `{"1030.8": "YYYY-MM-DD", ...}` mapping section identifier -> latest `amendment_date`. Non-fatal if this call fails — log and continue with `{}`.
5. Return ONE FetchResult for the XML with `meta = {"kind": "ecfr_xml", "ecfr_date": date, "cfr_title": title, "cfr_part": part, "section_amend_dates": {...}}`.

`normalize/ecfr_xml.py`:

```python
class EcfrXmlNormalizer:
    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]: ...
```

Behavior: parse with `lxml.etree`. Sections are `DIV8` elements with `TYPE="SECTION"`; the `N` attribute is the section number (e.g. `1030.8`), `HEAD` child is the heading. Body paragraphs are `P` elements (text content including inline markup via `itertext()`). Extract subsection labels from paragraph-leading designators like `(a)`, `(1)`, `(i)` using a regex on the paragraph text start; compute a rough `indent_level` from label nesting (letters=0, digits=1, romanettes=2 — best effort, 0 when unsure). Skip authority/source notes (`CITA`, `AUTH`, `SOURCE` elements). Output per section:
- `section_key = f"cfr/{title}/{N}"` (title from `fetched.meta["cfr_title"]`)
- `citation = f"{title} CFR § {N}"`
- Appendices (`DIV9`) may be included as their own units with `section_key = f"cfr/{title}/{part}/appendix-{label}"` — best effort, skip if malformed.

## M2 — PDF family: `adcoherent_rag/fetch/govinfo.py` + `adcoherent_rag/normalize/pdf.py`

`fetch/govinfo.py`:

```python
class PdfFetcher:
    def fetch(self, spec: SourceSpec) -> list[FetchResult]: ...
    def fetch_audit_copy(self, spec: SourceSpec) -> FetchResult: ...
```

- `fetch`: plain download of `spec.url` (follows redirects — govinfo link service redirects to the annual-edition PDF). Verify content looks like a PDF (`%PDF` magic or content-type); raise FetchError otherwise. meta kind `"generic_pdf"`.
- `fetch_audit_copy`: same download but meta kind `"audit_pdf"`, plus `meta["govinfo_package_id"]` extracted from the final URL when it matches `pkg/(CFR-\d{4}-title\d+-vol\d+)` (None-safe). Used by the pipeline to store the official PDF snapshot alongside eCFR XML for CFR sources.

`normalize/pdf.py`:

```python
class PdfNormalizer:
    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]: ...
```

- Extract text per page with PyMuPDF (`import fitz` lazily).
- Split into sections on citation-style headings (regex for `§ 123.45`, `Sec. 12-34`, `SECTION 5.` at line start). If headings are found: one SectionUnit per heading, `section_key = f"{spec.id}/{normalized-citation}"`, citation = the matched heading text.
- Fallback when no structure detected: one SectionUnit per ~3 pages, `section_key = f"{spec.id}/pages-{start}-{end}"`, `citation = f"{spec.citation or spec.name} (pp. {start}-{end})"`.
- Paragraphs: split on blank lines; label = leading `(a)`-style designator when present.

## M3 — Federal HTML: `adcoherent_rag/fetch/uscode.py` + `adcoherent_rag/fetch/finra.py` + `adcoherent_rag/normalize/html_generic.py`

`fetch/uscode.py`:

```python
class UscodeHtmlFetcher:
    def fetch(self, spec: SourceSpec) -> list[FetchResult]: ...
```

- Parse `granuleid:USC-prelim-title{T}-section{S}` from `spec.url` to learn title/section.
- The citation may list extra sections ("12 U.S.C. §§ 5531, 5536") — fetch each additional section by substituting the section number in the granuleid URL.
- One FetchResult per section, meta `{"kind": "uscode_html", "usc_title": T, "usc_section": S}`.

`fetch/finra.py`:

```python
class FinraFetcher:
    def fetch(self, spec: SourceSpec) -> list[FetchResult]: ...
```

- GET the FINRA rulebook page (`spec.url`). meta `{"kind": "finra_html", "rule_number": "2210"}` (parse rule number from URL tail). Send browser-like Accept headers; the page may block generic clients — surface a clear FetchError if so.

`normalize/html_generic.py`:

```python
def extract_main_text(html: str) -> str: ...
def split_labeled_paragraphs(text: str) -> list[Paragraph]: ...

class UscodeHtmlNormalizer:
    def normalize(self, fetched, spec) -> list[SectionUnit]: ...

class FinraHtmlNormalizer:
    def normalize(self, fetched, spec) -> list[SectionUnit]: ...

class GenericHtmlNormalizer:
    def normalize(self, fetched, spec) -> list[SectionUnit]: ...
```

- `extract_main_text`: bs4 — drop script/style/nav/header/footer/aside, prefer `<main>`/`<article>`/largest content div, return newline-joined text. This helper is REUSED by M4 (statute_html imports it from here).
- `split_labeled_paragraphs`: split text into `Paragraph`s, detecting leading `(a)` / `(1)` / `1.` designators. Also reused by M4.
- `UscodeHtmlNormalizer`: one SectionUnit per FetchResult. `section_key = f"usc/{title}/{section}"`, `citation = f"{title} U.S.C. § {section}"`. uscode.house.gov markup: heading in elements with class `section-head`; body in `statutory-body` / `statutory-body-1em` etc. — fall back to `extract_main_text`.
- `FinraHtmlNormalizer`: `section_key = f"finra/{rule_number}"`, `citation = f"FINRA Rule {rule_number}"`. Extract the rule text region; drop site chrome and "Selected Notices" cruft where feasible.
- `GenericHtmlNormalizer`: single SectionUnit from `extract_main_text`, `section_key = spec.id`, `citation = spec.citation or spec.name`.

## M4 — State scrapers: `adcoherent_rag/fetch/states.py` + `adcoherent_rag/normalize/statute_html.py`

`fetch/states.py`:

```python
class StateFetcher:
    def fetch(self, spec: SourceSpec) -> list[FetchResult]: ...

IMPLEMENTED_JURISDICTIONS: set[str]  # {"US-CA","US-NY","US-TX","US-FL","US-IL","US-MA","US-NJ"}
```

- Dispatch on `spec.jurisdiction` to a per-state function; unknown jurisdiction -> `FetchError(f"no scraper implemented yet for {spec.jurisdiction}")`.
- Every FetchResult: meta `{"kind": "state_html", "section_hint": "<section number>", "citation_hint": "<human citation>"}`.
- Per-state strategy (best effort — each section fetch is individually try/excepted; if EVERY section for a state fails, raise FetchError; partial success is fine and should log a warning):
  - **US-TX** (`us-tx-udap`): static HTML `https://statutes.capitol.texas.gov/Docs/BC/htm/BC.17.htm` — ONE FetchResult for the whole chapter page; the normalizer splits on `Sec. 17.41.`-style headings. section_hint "17" (chapter).
  - **US-CA** (`us-ca-udap`): section pages `https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=BPC&sectionNum={n}` for n in 17200, 17500, 17501, 17502, 17505, 17505.5, 17508, 17509 and `lawCode=CIV&sectionNum=1770`. citation_hint e.g. "Cal. Bus. & Prof. Code § 17500" / "Cal. Civ. Code § 1770".
  - **US-NY** (`us-ny-udap`): `https://www.nysenate.gov/legislation/laws/GBS/349` and `/350`, plus `/350-A`, `/350-D` (skip on 404). citation_hint "N.Y. Gen. Bus. Law § 349" etc.
  - **US-FL** (`us-fl-udap`): Online Sunshine section pages `http://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0500-0599/0501/Sections/0501.{n}.html` for n in 201, 202, 203, 204, 2041, 2075, 2077, 211, 212, 213 (zero-padded as the site expects; skip 404s). citation_hint "Fla. Stat. § 501.204" style.
  - **US-IL** (`us-il-udap`): fetch the act listing `https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=1219&ChapterID=67` (Consumer Fraud Act, 815 ILCS 505) as one page; if that ActID 404s, fetch the chapter listing from `spec.url` and follow the first link whose text contains "Consumer Fraud". One FetchResult, section_hint "815-505".
  - **US-MA** (`us-ma-udap`): section pages `https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXV/Chapter93A/Section{n}` for n in 1, 2, 3, 4, 9, 11. citation_hint "Mass. Gen. Laws ch. 93A, § 2" style.
  - **US-NJ** (`us-nj-udap`): try `https://lis.njleg.state.nj.us/nxt/gateway.dll?f=templates&fn=default.htm` alternatives are unreliable — attempt `https://www.njleg.state.nj.us/laws-constitution/statutes` first; if no statute text is extractable (very likely, it's a JS viewer), raise `FetchError("NJ statutes viewer requires manual deep-link resolution")` so the pipeline logs it cleanly. Leave a code comment explaining the manual step.
- Politeness: `time.sleep(0.5)` between section requests to the same host.

`normalize/statute_html.py`:

```python
class StateHtmlNormalizer:
    def normalize(self, fetched, spec) -> list[SectionUnit]: ...
```

- Import `extract_main_text` / `split_labeled_paragraphs` from `..normalize.html_generic`.
- Single-section pages (CA/NY/FL/MA): one SectionUnit; `section_key = f"{spec.jurisdiction.lower()}/{section_hint}"`; `citation = citation_hint`.
- Chapter pages (TX, IL): split the extracted text on section-heading regexes (`Sec\.\s+17\.\d+`, `Sec\.\s+\d+[a-z]?\.` / ILCS "505/2" markers). One SectionUnit per detected section: TX `section_key = f"us-tx/bc/{num}"`, citation "Tex. Bus. & Com. Code § 17.46"; IL `section_key = f"us-il/815-505/{num}"`, citation "815 ILCS 505/2".

## M5 — Chunking + embeddings: `adcoherent_rag/chunk/chunker.py` + `adcoherent_rag/embed/embedder.py`

`chunk/chunker.py`:

```python
def chunk_section(unit: SectionUnit, spec: SourceSpec, frameworks: list[str]) -> list[Chunk]: ...
```

- Group paragraphs by TOP-LEVEL subsection label: a new group starts at each paragraph whose label matches `^\([a-z]+\)$` (single-letter groups like `(a)`, `(b)`); nested labels and unlabeled prose stay with the current group. Text before the first labeled paragraph is its own group (label None).
- Each group becomes one Chunk when `len(text) <= config.CHUNK_MAX_CHARS`; otherwise split the group into windows of ~`CHUNK_TARGET_CHARS` on sentence boundaries with `CHUNK_OVERLAP_CHARS` overlap (all windows share the group's `subsection_label`).
- `context_header = f"{unit.citation} — {unit.heading}"` (+ f" — {label}" when the group has one); handle heading None.
- `chunk_index` increments across the whole section (0-based).
- `metadata = {"source_id": spec.id, "jurisdiction": spec.jurisdiction, "authority": spec.authority, "frameworks": frameworks, "topics": list(spec.topics), "citation": unit.citation, "section_key": unit.section_key}`.
- Never emit empty/whitespace-only chunks; skip sections with no text.

`embed/embedder.py`:

```python
class BaseEmbedder:
    model_name: str
    dim: int
    def encode(self, texts: list[str]) -> list[list[float]]: ...

class SentenceTransformerEmbedder(BaseEmbedder): ...
class FakeEmbedder(BaseEmbedder): ...

def get_embedder() -> BaseEmbedder: ...
```

- `SentenceTransformerEmbedder`: lazy `from sentence_transformers import SentenceTransformer`; model `config.EMBEDDING_MODEL_NAME`; `encode(..., batch_size=config.EMBEDDING_BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False)`; returns plain python lists. Load the model once (cached on the instance).
- `FakeEmbedder`: deterministic — seed a `hashlib.sha256` of the text into `random.Random`, produce a `config.EMBEDDING_DIM` unit-normalized vector. `model_name = "fake"`.
- `get_embedder()` returns FakeEmbedder when `config.EMBEDDING_FAKE` else SentenceTransformerEmbedder.

## M6 — Storage + retrieval: `adcoherent_rag/store/db.py` + `adcoherent_rag/store/repository.py` + `adcoherent_rag/retrieval/hybrid.py`

`store/db.py`:

```python
def get_connection() -> psycopg.Connection: ...
def init_db(conn) -> None: ...
```

- psycopg 3, `row_factory=dict_row`, autocommit OFF; `pgvector.psycopg.register_vector(conn)`. Raise a clear RuntimeError when `config.DATABASE_URL` is empty.
- `init_db`: execute `schema.sql` (read from package dir), commit; then create the ANN index: try `create index if not exists rag_chunks_embedding_idx on rag_chunks using hnsw (embedding vector_cosine_ops)`; on error (older pgvector), rollback and try `using ivfflat (embedding vector_cosine_ops) with (lists = 100)`; if that also fails, rollback and log a warning (retrieval still works, just seq-scan).

`store/repository.py` (all functions take `conn` first; caller commits):

```python
def upsert_sources(conn, specs: list[SourceSpec], manifest_ver: str) -> None
def latest_snapshot_sha(conn, source_id: str, kind: str) -> str | None
def record_snapshot(conn, fetched: FetchResult, storage_path: str, sha256: str) -> str
def get_current_version(conn, source_id: str, section_key: str) -> dict | None
def upsert_section_version(conn, unit: SectionUnit, snapshot_id: str | None,
                           effective_start: date, text_sha256: str) -> tuple[str, bool]
def replace_chunks(conn, version_id: str, spec: SourceSpec, chunks: list[Chunk],
                   embeddings: list[list[float]], embedding_model: str, embedding_dim: int) -> int
def start_ingest_run(conn) -> str
def finish_ingest_run(conn, run_id: str, stats: dict) -> None
def log_ingest_event(conn, run_id: str, source_id: str | None, status: str, detail: dict) -> None
def corpus_stats(conn) -> dict
```

- `upsert_sources`: insert-or-update every manifest row incl. `frameworks_for(spec)` and topics (jsonb) — `on conflict (id) do update`, bump `updated_at`.
- `upsert_section_version` (the versioned-upsert core): look up current version (`effective_end is null`) for (source_id, section_key). Same `text_sha256` -> return `(existing_id, False)`. Different -> close the old row (`effective_end = effective_start` of the new one, `superseded_by = new_id`) and insert the new row; return `(new_id, True)`. First version -> plain insert. Also guard the unique constraint: if a row for the same (source_id, section_key, effective_start) already exists with different text, update it in place (same-day re-ingest correction) — document this exception to append-only.
- `replace_chunks`: `delete from rag_chunks where version_id = %s` then batch-insert (use `executemany` or `COPY`); denormalize `source_id`, `jurisdiction`, `frameworks` from spec/`frameworks_for`. Embedding passed as `pgvector` list.
- `corpus_stats`: counts per source (versions, current versions, chunks), total chunks, embedding models present.

`retrieval/hybrid.py`:

```python
def retrieve(conn, embedder, query: str, *, k: int = 8,
             frameworks: list[str] | None = None,
             jurisdictions: list[str] | None = None,
             source_ids: list[str] | None = None,
             as_of: date | None = None,
             candidates: int = config.RETRIEVAL_CANDIDATES) -> list[RetrievalResult]
```

- One SQL statement: CTE `filtered` joins rag_chunks c + rag_regulation_versions v with the effective-window predicate (`as_of` None -> `v.effective_end is null`; else `v.effective_start <= %s and (v.effective_end is null or v.effective_end > %s)`) and optional filters (`c.frameworks && %s::text[]`, `c.jurisdiction = any(%s)`, `c.source_id = any(%s)`), plus `c.embedding is not null`.
- CTE `vec`: rank by `embedding <=> %s::vector` limit candidates. CTE `lex`: `tsv @@ websearch_to_tsquery('english', %s)` ranked by `ts_rank_cd` limit candidates.
- Full outer join on chunk id; score `coalesce(1.0/(:rrf + vec.rank), 0) + coalesce(1.0/(:rrf + lex.rank), 0)` with `config.RRF_K`; order desc, limit k. Return RetrievalResults with both ranks (None when absent).
- Embed the query with `embedder.encode([query])[0]`.

## M7 — Orchestration: `adcoherent_rag/pipeline.py` + `adcoherent_rag/cli.py`

`pipeline.py`:

```python
HANDLERS: dict[str, tuple[Fetcher, Normalizer]]  # family -> (fetcher, normalizer) instances

def ingest_sources(source_ids: list[str] | None = None, *, force: bool = False,
                   dry_run: bool = False, conn=None) -> dict
def sync_sources(conn=None) -> int
```

- Families: `cfr -> (EcfrFetcher, EcfrXmlNormalizer)`, `uscode_html -> (UscodeHtmlFetcher, UscodeHtmlNormalizer)`, `finra_html -> (FinraFetcher, FinraHtmlNormalizer)`, `state_html -> (StateFetcher, StateHtmlNormalizer)`, `generic_pdf -> (PdfFetcher, PdfNormalizer)`, `generic_html -> (fetch via http.fetch_url kind "generic_html", GenericHtmlNormalizer)`.
- `ingest_sources` flow (default source set = `manifest.default_ingest_sources()`):
  1. open conn (unless injected), `sync_sources`, `start_ingest_run`.
  2. per source (each wrapped in try/except -> `log_ingest_event(..., "error", {"error": str(e)})`, rollback to savepoint, continue):
     - family `manual_stub` -> event "skipped" with the reason; continue.
     - fetch -> for each FetchResult: sha256; if not force and sha == `latest_snapshot_sha(source_id, kind)` -> event "unchanged", skip this result entirely.
     - write raw bytes to `config.RAW_STORAGE_DIR/{source_id}/{ts}_{kind}{ext}`; `record_snapshot`.
     - CFR extra: also `PdfFetcher().fetch_audit_copy(spec)` snapshot (try/except, non-fatal) — snapshot only, never normalized.
     - normalize -> for each SectionUnit: `effective_start` = eCFR amend date for that section when available in `fetched.meta["section_amend_dates"]` (key = section number like "1030.8") else `fetched.fetched_at.date()`; `upsert_section_version`; when version is new (or force): `chunk_section` -> embed all chunk `embedding_input`s -> `replace_chunks`.
     - `dry_run`: do fetch+normalize+chunk but skip all DB writes and snapshots; report counts.
     - commit after each source; event "stored" with counts {sections, new_versions, chunks}.
  3. `finish_ingest_run` with aggregate stats; return the stats dict.
- Use a psycopg savepoint (or per-source commit + fresh transaction) so one failing source never poisons the transaction for the rest.

`cli.py` (argparse, `main()` + `if __name__ == "__main__": main()`; run as `python -m adcoherent_rag.cli`):

- `init-db` — connect, `init_db`, print confirmation.
- `sync-sources` — upsert manifest into rag_sources, print count.
- `ingest [--source-id ID ...] [--force] [--dry-run]` — default = tier-1 + priority states; prints per-source progress lines and a final summary table.
- `retrieve QUERY [--k 8] [--framework F ...] [--jurisdiction J ...] [--as-of YYYY-MM-DD]` — prints ranked results: score, citation, header, first ~300 chars.
- `stats` — prints `corpus_stats`.
- Also create `adcoherent_rag/__main__.py` containing `from .cli import main; main()`.

## M8 — Tests: `tests/` (pytest, no network, no DB, no model download)

Files: `tests/conftest.py`, `tests/test_manifest.py`, `tests/test_chunker.py`, `tests/test_ecfr_normalizer.py`, `tests/test_embedder.py`, `tests/test_html_normalizers.py`, plus fixture data under `tests/fixtures/`.

- `conftest.py`: set `EMBEDDING_FAKE=1` env BEFORE importing the package; add rag-engine dir to `sys.path` if needed; helper factory for SourceSpec/FetchResult.
- `test_manifest.py`: loads the real manifest (config resolves the path); asserts 79 sources, tier-1 count == 22, `default_ingest_sources` includes the 7 priority-state UDAP ids + excludes tier 3 and non-priority states; `parse_cfr_citation` against the 5 tricky citations from the manifest ("12 CFR Part 1026 (advertising: §§ 1026.16, 1026.24)", "17 CFR 275.206(4)-1", "17 CFR 230.482", "47 CFR § 64.1200", "16 CFR Part 255"); `source_family` spot-checks incl. MANUAL_STUB_SOURCES.
- `test_ecfr_normalizer.py`: write a small synthetic eCFR XML fixture (2 DIV8 sections with HEAD + labeled `P`s) in `tests/fixtures/ecfr_sample.xml`; assert section_keys, citations, headings, paragraph labels.
- `test_chunker.py`: build a SectionUnit with subsections (a)-(c), one oversize; assert grouping by top-level label, size limits (<= CHUNK_MAX_CHARS + header tolerance), overlap on splits, chunk_index continuity, metadata fields present, empty sections yield [].
- `test_embedder.py`: FakeEmbedder determinism, dim == config.EMBEDDING_DIM, unit norm (±1e-6), `get_embedder()` returns FakeEmbedder under EMBEDDING_FAKE.
- `test_html_normalizers.py`: small inline HTML fixtures for `extract_main_text` (drops nav/script), `split_labeled_paragraphs`, `UscodeHtmlNormalizer` (synthetic uscode-like HTML), `StateHtmlNormalizer` single-section page, and TX chapter-splitting via a synthetic `Sec. 17.41.` page.
- Do NOT test fetchers against the live network; do NOT import sentence_transformers or fitz.
