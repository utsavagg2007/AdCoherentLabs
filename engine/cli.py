"""Command-line entry point for the connected compliance engine.

    python -m engine.cli check --text "Get 5.99% APR!" --tier pro
    python -m engine.cli check --image ad.png --tier free --jurisdictions US-CA
    python -m engine.cli check --html-file page.html --tier design --out report.json
    python -m engine.cli check --text "..." --tier hobby --interactive
    python -m engine.cli check --text "..." --user reviewer@acme.com   # SaaS mode
    python -m engine.cli quota --user reviewer@acme.com
    python -m engine.cli selftest
    python -m engine.cli saas-selftest
    python -m engine.cli tiers

SaaS mode (--user): the product tier is FETCHED FROM SUPABASE (the org's
subscription via app.org_tier) — --tier is ignored — quota is consumed
before the run, and the run/layer outputs/findings/audit trail are
persisted to the SaaS schema.

Exit codes: 0 = passed, 2 = human_review (operator input still needed),
3 = llm_error, 4 = quota/permission rejected, 1 = bad usage / crash.
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
    """Operator-interference loop: prompt for guidance, re-run one round.

    In SaaS mode (--user) the resume goes through engine.saas.resume_run,
    so every operator round is persisted and audited like the original."""
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
        if getattr(args, "user", None):
            from .saas import resume_run

            result = resume_run(
                user=args.user,
                run=result.provenance["saas"]["analysis_run_id"],
                guidance=guidance, as_of=args.as_of_date, include_asset=True,
            )
        else:
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

    if args.user:
        from .saas import SaasError, run_for_user

        print("SaaS mode: tier comes from the org's subscription in Supabase"
              " (--tier is ignored)")
        try:
            result = run_for_user(
                user=args.user, org=args.org,
                asset_id=args.asset_id,
                image_path=image, text=text, html=html,
                title=args.title,
                target_jurisdictions=args.jurisdictions,
                as_of=args.as_of_date,
                max_llm_rounds=args.max_llm_rounds,
                provider=provider,
                retriever=retriever,
                include_asset=True,
            )
        except SaasError as exc:
            print(f"rejected: {exc}", file=sys.stderr)
            return 4
        saas = result.provenance.get("saas", {})
        print(f"persisted: org {saas.get('org_id')}  "
              f"run {saas.get('analysis_run_id')}  "
              f"(tier {result.tier} fetched from Supabase)")
    else:
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


def cmd_saas_selftest(_args) -> int:
    from .saas_selftest import main as saas_selftest_main

    return saas_selftest_main()


def cmd_quota(args) -> int:
    """Quota/tier snapshot for a user's org, straight from the DB."""
    from .saas import SaasError, SupabaseDataPlane

    try:
        with SupabaseDataPlane() as db:
            user = db.resolve_user(args.user)
            org_id, role = db.resolve_org(user["id"], args.org)
            ent = db.get_entitlements(org_id)
            quota = db.check_quota(org_id)
    except SaasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"user   {user['email']}  (role: {role}, "
          f"confirmed: {'yes' if user['confirmed'] else 'NO'})")
    print(f"org    {org_id}")
    print(f"tier   {ent.tier}  ->  {ent.llm_provider}:{ent.llm_model}  "
          f"(max {ent.max_output_tokens:,} out tokens)")
    print(f"quota  {quota.get('used', '?')} used / "
          f"{quota.get('limit') if quota.get('limit') is not None else 'uncapped'}"
          f"  remaining: {quota.get('remaining', 'n/a')}")
    print(f"api    {'yes' if ent.api_access else 'no'}   "
          f"frameworks: {ent.frameworks}")
    for d in ent.drift:
        print(f"DRIFT  {d}  <- plan_entitlements and engine TIERS disagree")
    return 0


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
                   help="product tier (selects the LLM; default free); "
                        "IGNORED with --user (the DB decides)")
    c.add_argument("--user", default=None,
                   help="SaaS mode: auth user id or email - tier is fetched "
                        "from the org's Supabase subscription, quota enforced, "
                        "run + findings + audit persisted")
    c.add_argument("--org", default=None,
                   help="org uuid (only needed with --user when the user "
                        "belongs to several orgs; membership is verified)")
    c.add_argument("--title", default=None,
                   help="submission title stored in Supabase (--user mode)")
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

    ss = sub.add_parser("saas-selftest",
                        help="LIVE Supabase integration proof: temp org/user, "
                             "tier fetch, quota, persistence, audit chain "
                             "(stub LLM - no API spend)")
    ss.set_defaults(fn=cmd_saas_selftest)

    q = sub.add_parser("quota", help="tier + quota snapshot for a user's org")
    q.add_argument("--user", required=True, help="auth user id or email")
    q.add_argument("--org", default=None, help="org uuid if member of several")
    q.set_defaults(fn=cmd_quota)

    t = sub.add_parser("tiers", help="print the tier -> model/OCR matrix")
    t.set_defaults(fn=cmd_tiers)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
