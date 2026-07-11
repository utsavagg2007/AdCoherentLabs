"""Command-line entry points.

    python -m adcoherent_rag.cli init-db
    python -m adcoherent_rag.cli sync-sources
    python -m adcoherent_rag.cli ingest [--source-id ID ...] [--force] [--dry-run]
    python -m adcoherent_rag.cli retrieve "query" [--k 8] [--framework F ...]
                                  [--jurisdiction J ...] [--as-of YYYY-MM-DD]
    python -m adcoherent_rag.cli review nlp-result.json --tier pro
                                  [--jurisdiction J ...] [--as-of YYYY-MM-DD]
                                  [--out review.json]
    python -m adcoherent_rag.cli stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _cmd_init_db(_args: argparse.Namespace) -> int:
    from .store.db import get_connection, init_db

    with get_connection() as conn:
        init_db(conn)
    print("Schema initialized (tables, indexes, vector extension).")
    return 0


def _cmd_sync_sources(_args: argparse.Namespace) -> int:
    from .pipeline import sync_sources

    count = sync_sources()
    print(f"Synced {count} manifest sources into rag_sources.")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .pipeline import ingest_sources

    stats = ingest_sources(
        args.source_id or None,
        all_sources=args.all,
        force=args.force,
        dry_run=args.dry_run,
    )
    print()
    print(f"{'source':<38} {'status':<10} {'sections':>8} {'new_ver':>8} {'chunks':>7}")
    print("-" * 76)
    for source_id, outcome in stats["per_source"].items():
        print(
            f"{source_id:<38} {outcome['status']:<10} "
            f"{outcome.get('sections', 0):>8} {outcome.get('new_versions', 0):>8} "
            f"{outcome.get('chunks', 0):>7}"
        )
        if outcome.get("error"):
            print(f"{'':<38}   error: {outcome['error'][:90]}")
        if outcome.get("reason"):
            print(f"{'':<38}   reason: {outcome['reason'][:90]}")
    print("-" * 76)
    print(
        f"totals: {stats['stored']} stored, {stats['unchanged']} unchanged, "
        f"{stats['skipped']} skipped, {stats['errors']} errors — "
        f"{stats['sections']} sections, {stats['new_versions']} new versions, "
        f"{stats['chunks']} chunks"
        + (" (dry run — nothing written)" if stats["dry_run"] else "")
    )
    return 1 if stats["errors"] and not stats["stored"] else 0


def _cmd_retrieve(args: argparse.Namespace) -> int:
    from .embed.embedder import get_embedder
    from .retrieval.hybrid import retrieve
    from .store.db import get_connection

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    with get_connection() as conn:
        results = retrieve(
            conn,
            get_embedder(),
            args.query,
            k=args.k,
            frameworks=args.framework or None,
            jurisdictions=args.jurisdiction or None,
            as_of=as_of,
        )
    if not results:
        print("No results. (Is the corpus ingested? Do the filters match?)")
        return 1
    for i, r in enumerate(results, 1):
        ranks = (
            f"vec#{r.vector_rank}" if r.vector_rank else "vec:-",
            f"lex#{r.lexical_rank}" if r.lexical_rank else "lex:-",
        )
        window = " ".join(r.text.split())
        print(f"\n{i}. [{r.score:.4f}] {r.context_header}  ({', '.join(ranks)})")
        print(f"   source={r.source_id}  effective {r.effective_start} → "
              f"{r.effective_end or 'current'}")
        print(f"   {window[:300]}{'…' if len(window) > 300 else ''}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .embed.embedder import get_embedder
    from .review.engine import ReviewError, review_asset
    from .store.db import get_connection

    nlp_result = json.loads(Path(args.nlp_json).read_text())
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    try:
        with get_connection() as conn:
            result = review_asset(
                nlp_result,
                args.tier,
                conn=conn,
                embedder=get_embedder(),
                jurisdictions=args.jurisdiction or None,
                as_of=as_of,
            )
    except ReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n")
        print(f"Review written to {args.out} "
              f"({len(result['findings'])} findings, tier={args.tier}).")
    else:
        print(rendered)
    return 0


def _cmd_stats(_args: argparse.Namespace) -> int:
    from .store.db import get_connection
    from .store.repository import corpus_stats

    with get_connection() as conn:
        stats = corpus_stats(conn)
    print(f"{'source':<38} {'jurisdiction':<14} {'versions':>8} {'current':>8} {'chunks':>7}")
    print("-" * 80)
    for row in stats["per_source"]:
        print(
            f"{row['source_id']:<38} {row['jurisdiction']:<14} "
            f"{row['versions']:>8} {row['current_versions']:>8} {row['chunks']:>7}"
        )
    print("-" * 80)
    print(f"total chunks: {stats['total_chunks']}  "
          f"embedding models: {stats['embedding_models']}")
    if stats["last_run"]:
        run = stats["last_run"]
        run_stats = run["stats"]
        if isinstance(run_stats, str):
            run_stats = json.loads(run_stats)
        print(f"last run: {run['started_at']} -> {run['finished_at']}  {run_stats}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adcoherent_rag", description="AdCoherent regulatory RAG engine"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create schema + indexes").set_defaults(
        func=_cmd_init_db
    )
    sub.add_parser("sync-sources", help="upsert the manifest into rag_sources"
                   ).set_defaults(func=_cmd_sync_sources)

    p_ingest = sub.add_parser("ingest", help="fetch, normalize, embed, store")
    p_ingest.add_argument("--source-id", action="append",
                          help="ingest only this manifest source id (repeatable)")
    p_ingest.add_argument("--all", action="store_true",
                          help="ingest the full manifest (all 50 states + DC "
                               "+ tier-3 references), not just tier-1 + priority states")
    p_ingest.add_argument("--force", action="store_true",
                          help="re-ingest even when content is unchanged")
    p_ingest.add_argument("--dry-run", action="store_true",
                          help="fetch/normalize/chunk only; no DB writes")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_ret = sub.add_parser("retrieve", help="hybrid RRF retrieval")
    p_ret.add_argument("query")
    p_ret.add_argument("--k", type=int, default=8)
    p_ret.add_argument("--framework", action="append",
                       help="filter by framework label, e.g. Reg_DD (repeatable)")
    p_ret.add_argument("--jurisdiction", action="append",
                       help="filter by jurisdiction, e.g. US-CA (repeatable)")
    p_ret.add_argument("--as-of", help="audit replay date YYYY-MM-DD")
    p_ret.set_defaults(func=_cmd_retrieve)

    p_rev = sub.add_parser(
        "review", help="LLM compliance review of an NLP-layer asset result"
    )
    p_rev.add_argument("nlp_json", help="path to the NLP result JSON for one asset")
    p_rev.add_argument("--tier", required=True,
                       choices=["free", "hobby", "pro", "design", "enterprise"],
                       help="SaaS tier (selects model + token budget)")
    p_rev.add_argument("--jurisdiction", action="append",
                       help="restrict retrieval to a jurisdiction, e.g. US-CA (repeatable)")
    p_rev.add_argument("--as-of", help="audit replay date YYYY-MM-DD")
    p_rev.add_argument("--out", help="write the review JSON here instead of stdout")
    p_rev.set_defaults(func=_cmd_review)

    sub.add_parser("stats", help="corpus statistics").set_defaults(func=_cmd_stats)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
