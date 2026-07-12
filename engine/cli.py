"""Command-line entry point for the connected compliance engine.

    python -m engine.cli check --text "Get 5.99% APR!" --tier pro
    python -m engine.cli check --image ad.png --tier free --jurisdictions US-CA
    python -m engine.cli check --html-file page.html --tier design --out report.json
    python -m engine.cli check --text "..." --tier hobby --interactive
    python -m engine.cli selftest
    python -m engine.cli tiers

Exit codes: 0 = passed, 2 = human_review (operator input still needed),
3 = llm_error, 1 = bad usage / crash.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from .orchestrator import (
    DEFAULT_MAX_LLM_ROUNDS,
    resume_with_human_guidance,
    run_compliance_engine,
)
from .report import EngineRunResult
from .tiers import PRODUCT_TIERS, TIERS, ocr_tier_for

_EXIT_BY_STATUS = {"passed": 0, "human_review": 2, "llm_error": 3}


def _print_result(result: EngineRunResult) -> None:
    print("-" * 72)
    for line in result.summary_lines():
        print(line)
    print("-" * 72)


def _write_out(result: EngineRunResult, out: str | None) -> None:
    if not out:
        return
    payload = result.model_dump(mode="json")
    Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    print(f"full report written to {out}")


def _interactive_loop(result: EngineRunResult, asset: dict, args) -> EngineRunResult:
    """Operator-interference loop: prompt for guidance, re-run one round."""
    while result.status == "human_review":
        print()
        print("The engine needs operator interference. Outstanding items:")
        for ins in (result.human_review.instructions if result.human_review else []):
            print(f"  * {ins.get('check_id')}: {ins.get('instruction')}")
        print("Enter guidance for the model (empty line or Ctrl-C to stop):")
        try:
            guidance = input("guidance> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nstopping - run left in human_review state")
            break
        if not guidance:
            print("no guidance given - run left in human_review state")
            break
        result = resume_with_human_guidance(
            asset, guidance,
            product_tier=args.tier, previous=result,
            as_of=args.as_of_date, include_asset=True,
        )
        _print_result(result)
    return result


def cmd_check(args) -> int:
    if args.verbose:
        logging.basicConfig(level=logging.INFO,
                            format="%(levelname)s %(name)s: %(message)s")
    text = args.text
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    html = None
    if args.html_file:
        html = Path(args.html_file).read_text(encoding="utf-8")
    image: str | list[str] | None = None
    if args.image:
        image = args.image if len(args.image) > 1 else args.image[0]

    sources = [s for s in (image, text, html) if s is not None]
    if len(sources) != 1:
        print("error: provide exactly one input: --text | --text-file | "
              "--image ... | --html-file", file=sys.stderr)
        return 1

    args.as_of_date = date.fromisoformat(args.as_of) if args.as_of else None

    provider = retriever = None
    if args.stub_llm:
        from .selftest import StubProvider, _clear_review, _extract_asset, stub_retriever
        from adcoherent_rag.review.providers import CompletionResult

        class _AlwaysClear(StubProvider):
            def complete(self, tier, system, user):
                return CompletionResult(
                    payload=_clear_review(_extract_asset(user)),
                    model="stub-compliance-llm")

        provider, retriever = _AlwaysClear(), stub_retriever
        print("NOTE: --stub-llm - deterministic offline stand-ins for the "
              "LLM and retrieval; wiring demo only, NOT a compliance review.")

    result = run_compliance_engine(
        asset_id=args.asset_id,
        image_path=image, text=text, html=html,
        product_tier=args.tier,
        target_jurisdictions=args.jurisdictions,
        as_of=args.as_of_date,
        max_llm_rounds=args.max_llm_rounds,
        provider=provider,
        retriever=retriever,
        include_asset=True,
    )
    _print_result(result)

    if args.interactive and result.status == "human_review":
        result = _interactive_loop(result, result.asset, args)

    if not args.include_asset:
        result.asset = None
    _write_out(result, args.out)
    return _EXIT_BY_STATUS.get(result.status, 1)


def cmd_selftest(_args) -> int:
    from .selftest import main as selftest_main

    return selftest_main()


def cmd_tiers(_args) -> int:
    print(f"{'tier':<11} {'provider':<10} {'model':<18} {'ocr (layer 1)':<22} "
          f"{'max out tok':>11} {'chunks/fw':>9} {'ctx chars':>10}")
    for name in PRODUCT_TIERS:
        t = TIERS[name]
        ocr = ocr_tier_for(name)
        ocr_label = "local (PaddleOCR)" if ocr == "free" else "Google Vision"
        print(f"{name:<11} {t.provider:<10} {t.model:<18} {ocr_label:<22} "
              f"{t.max_output_tokens:>11,} {t.max_chunks_per_framework:>9} "
              f"{t.max_context_chars:>10,}")
    print("\nLLM callback budget per run: 1 initial call + 2 rule-engine "
          f"callbacks (DEFAULT_MAX_LLM_ROUNDS={DEFAULT_MAX_LLM_ROUNDS}); "
          "then operator interference.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m engine.cli",
        description="AdCoherent Labs - connected 4-layer ad-compliance engine",
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="run one ad through all four layers")
    c.add_argument("--text", help="ad copy as a literal string")
    c.add_argument("--text-file", help="path to a UTF-8 text file with the ad copy")
    c.add_argument("--image", nargs="+",
                   help="path(s) to ad image(s); multiple paths = carousel")
    c.add_argument("--html-file", help="path to an HTML creative")
    c.add_argument("--tier", default="free", choices=list(PRODUCT_TIERS),
                   help="product tier (selects the LLM; default free)")
    c.add_argument("--jurisdictions", nargs="*", default=None,
                   help="targeting, e.g. US or US-CA US-NY (state checks "
                        "run only when given)")
    c.add_argument("--as-of", default=None,
                   help="audit replay date YYYY-MM-DD (regulations effective "
                        "on that date)")
    c.add_argument("--asset-id", default=None, help="stable id for this asset")
    c.add_argument("--max-llm-rounds", type=int, default=DEFAULT_MAX_LLM_ROUNDS,
                   help="total LLM calls before human review (default "
                        f"{DEFAULT_MAX_LLM_ROUNDS} = 1 initial + 2 callbacks)")
    c.add_argument("--interactive", action="store_true",
                   help="on human_review, prompt for operator guidance and "
                        "re-run (repeat until passed or you stop)")
    c.add_argument("--stub-llm", action="store_true",
                   help="offline wiring demo: deterministic stub LLM + stub "
                        "retrieval (no API keys, no DB, NOT a real review)")
    c.add_argument("--out", default=None, help="write the full JSON report here")
    c.add_argument("--include-asset", action="store_true",
                   help="embed the AssetRepresentation in the JSON report")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("selftest",
                       help="offline wiring proof (stub LLM + stub retrieval)")
    s.set_defaults(fn=cmd_selftest)

    t = sub.add_parser("tiers", help="print the tier -> model/OCR matrix")
    t.set_defaults(fn=cmd_tiers)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
