"""Manifest loading, source classification, and framework routing.

The manifest (adcoherent_regulatory_sources.json) is the single source of
truth for what gets ingested. This module also maps each source to the
framework labels the NLP layer emits in routing.frameworks (e.g. "Reg_DD",
"FTC") so retrieval can be filtered per framework.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .models import SourceSpec

# ---------------------------------------------------------------------------
# Loading

def load_manifest(path: Path | None = None) -> list[SourceSpec]:
    raw = json.loads((path or config.MANIFEST_PATH).read_text())
    specs = []
    for s in raw["sources"]:
        specs.append(
            SourceSpec(
                id=s["id"],
                tier=int(s["tier"]),
                category=s["category"],
                jurisdiction=s["jurisdiction"],
                authority=s.get("authority"),
                citation=s.get("citation"),
                name=s["name"],
                url=s["url"],
                format=s.get("format", "html"),
                ingestion=s.get("ingestion", "html_scrape"),
                url_status=s.get("url_status"),
                update_cadence=s.get("update_cadence"),
                topics=tuple(s.get("topics", ())),
                notes=s.get("notes"),
            )
        )
    return specs


def manifest_version(path: Path | None = None) -> str:
    raw = json.loads((path or config.MANIFEST_PATH).read_text())
    return str(raw.get("version", "unknown"))


def get_source(source_id: str, specs: list[SourceSpec] | None = None) -> SourceSpec:
    for s in specs or load_manifest():
        if s.id == source_id:
            return s
    raise KeyError(f"source id not in manifest: {source_id}")


# ---------------------------------------------------------------------------
# Framework routing (must line up with the NLP layer's routing.frameworks)

FRAMEWORK_MAP: dict[str, list[str]] = {
    "ftc-act-section-5": ["FTC"],
    "ftc-endorsement-guides": ["FTC"],
    "ftc-consumer-reviews-rule": ["FTC"],
    "ftc-deceptive-pricing-guides": ["FTC"],
    "ftc-free-offer-guides": ["FTC"],
    "ftc-telemarketing-sales-rule": ["FTC"],
    "ftc-can-spam-rule": ["FTC", "CAN_SPAM"],
    "ftc-coppa": ["FTC", "COPPA"],
    "cfpb-reg-z-tila": ["Reg_Z"],
    "cfpb-reg-dd-tisa": ["Reg_DD"],
    "cfpb-reg-b-ecoa": ["Reg_B"],
    "cfpb-reg-m-leasing": ["Reg_M"],
    "cfpb-reg-n-map": ["Reg_N"],
    "cfpb-udaap-statute": ["UDAAP"],
    "fdic-part-328": ["FDIC"],
    "ncua-part-740": ["NCUA"],
    "sec-marketing-rule": ["SEC"],
    "sec-rule-482": ["SEC"],
    "sec-ica-rule-34b-1": ["SEC"],
    "finra-rule-2210": ["FINRA"],
    "fcc-tcpa-rules": ["TCPA"],
    "hud-fair-housing-advertising": ["FHA"],
}


def frameworks_for(spec: SourceSpec) -> list[str]:
    if spec.id in FRAMEWORK_MAP:
        base = list(FRAMEWORK_MAP[spec.id])
    elif spec.category in ("state_udap", "state_finreg"):
        base = ["STATE_UDAP"]
    elif spec.category == "secondary_reference":
        base = ["REFERENCE"]
    else:
        base = []
    if spec.jurisdiction not in ("US", "US-ALL-STATES") and spec.jurisdiction not in base:
        base.append(spec.jurisdiction)
    return base


# ---------------------------------------------------------------------------
# Handler-family resolution

# Sources whose official text has NO plain-HTTP scrape path (JS-only SPA
# viewers, LexisNexis/Westlaw-hosted codes) — and whose usual mirror (Justia)
# is bot-blocked. Skipped with an explicit per-source reason, never silently.
# Ingesting these needs a manual snapshot, a licensed feed, or a headless-
# browser worker (deliberately out of scope for v0).
# Live-probed 2026-07-05: every entry below returned an SPA shell, a
# doc-id-only viewer, or 403s from both official host and mirrors.
MANUAL_STUB_SOURCES: dict[str, str] = {
    "us-al-udap": "ALISON code browser is a JS SPA (no server-rendered statute text)",
    "us-ak-udap": "akleg.gov BASIS blocks non-browser clients (403) and is frame/JS based",
    "us-ar-udap": "official Arkansas Code is served only through a LexisNexis viewer",
    "us-ga-udap": "official O.C.G.A. is served only through a LexisNexis viewer",
    "us-in-udap": "iga.in.gov serves an SPA shell (no server-rendered statute text)",
    "us-la-udap": "legis.la.gov statute pages are opaque doc-id lookups (no stable cite URL)",
    "us-ms-udap": "official Miss. Code is LexisNexis-only; Justia mirror bot-blocks scrapers",
    "us-nm-udap": "nmonesource.com (Lexum viewer) has no server-rendered statute text",
    "us-ok-udap": "OSCN statute pages are opaque CiteID lookups (no stable cite URL)",
    "us-tn-udap": "official T.C.A. is LexisNexis-only; Justia mirror bot-blocks scrapers",
    "us-nj-udap": "njleg statutes viewer is JS-only (lis.njleg nxt gateway frames); "
                  "Justia mirror bot-blocks scrapers",
    "us-ny-dfs-crypto-ads": "23 NYCRR Part 200 text is published only on the "
                            "govt.westlaw.com unofficial NYCRR viewer (bot-protected); "
                            "DFS site links no PDF of the rule text",
}

_CFR_RE = re.compile(
    r"(?P<title>\d+)\s+C\.?F\.?R\.?\s+(?:Part\s+)?§*\s*(?P<part>\d+)"
    r"(?:\.(?P<section>[0-9A-Za-z().\-]+))?",
    re.IGNORECASE,
)


def parse_cfr_citation(citation: str) -> tuple[int, int, str | None]:
    """Return (title, part, section-or-None).

    "12 CFR Part 1030 (advertising: § 1030.8)"  -> (12, 1030, None)
    "17 CFR 230.482"                            -> (17, 230, "482")
    "47 CFR § 64.1200"                          -> (47, 64, "1200")
    """
    m = _CFR_RE.search(citation)
    if not m:
        raise ValueError(f"not a CFR citation: {citation!r}")
    return int(m.group("title")), int(m.group("part")), m.group("section")


def source_family(spec: SourceSpec) -> str:
    """Which fetch/normalize handler family a source belongs to.

    Families: cfr | uscode_html | finra_html | state_html | generic_pdf
              | generic_html | manual_stub
    """
    if spec.id in MANUAL_STUB_SOURCES:
        return "manual_stub"
    if spec.category == "federal_regulation" and spec.citation:
        try:
            parse_cfr_citation(spec.citation)
            return "cfr"
        except ValueError:
            pass
    if spec.category == "federal_statute":
        return "uscode_html"
    if spec.category == "sro_rule":
        return "finra_html"
    if spec.category in ("state_udap", "state_finreg"):
        return "state_html"
    if spec.format == "pdf":
        return "generic_pdf"
    return "generic_html"


# ---------------------------------------------------------------------------
# Ingest coverage selections

def default_ingest_sources(specs: list[SourceSpec] | None = None) -> list[SourceSpec]:
    """Default coverage: tier-1 federal + priority-state UDAP/finreg."""
    specs = specs or load_manifest()
    selected = []
    for s in specs:
        if s.tier == 1:
            selected.append(s)
        elif (
            s.category in ("state_udap", "state_finreg")
            and s.jurisdiction in config.PRIORITY_STATE_JURISDICTIONS
        ):
            selected.append(s)
    return selected


def all_ingest_sources(specs: list[SourceSpec] | None = None) -> list[SourceSpec]:
    """Full-manifest coverage: every source, all tiers (references included)."""
    return list(specs or load_manifest())
