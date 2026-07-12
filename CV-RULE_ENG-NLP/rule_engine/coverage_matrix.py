"""Regulatory coverage matrix: every source in the Regulatory Source
Directory (adcoherent_regulatory_sources.json) classified by how the
engine mechanizes it.

Mechanization values (exactly one per row):

  * ``structural``   — deterministic checks on the creative are possible
                       (wording, presence, geometry, numeric bounds);
  * ``coverage``     — the engine enforces that the LLM evaluated the
                       framework whenever the asset routes to it;
  * ``advisory``     — process/governance rule: the engine emits an
                       advisory flag (CheckResult scope="advisory")
                       naming it as applicable to the advertiser but out
                       of creative scope;
  * ``out_of_scope`` — not an advertising obligation at all; the reason
                       is recorded on the row.

Classification follows the directory's own architecture notes (encode
the organizational layer as deterministic rule-packs; PCI/NIST/
recordkeeping are process rules).

This table is part of the ruleset: it is versioned and hashed into
``rule_engine.version.ruleset_hash`` exactly like the lexicons, so any
reclassification changes the hash. Statuses: ``active`` (directory row,
classification in force), ``pending_directory_entry`` (framework family
classified ahead of its directory row; encoded so routing/enum support
exists on day one), ``reference_only`` (directory row that imposes no
obligation).

Determinism guard (see rule_engine/core.py): stdlib + contract modules
only.

Regenerate docs/coverage_matrix.md after any edit:
    python -m rule_engine.coverage_matrix > docs/coverage_matrix.md
"""

from __future__ import annotations

#: Bump on any row change; hashed into ruleset_hash.
#: 1.0.0 — classifies Regulatory Source Directory manifest 1.0.0 (79
#: sources) + 21 framework families classified ahead of directory entry.
COVERAGE_MATRIX_VERSION = "1.0.0"

#: Directory manifest this matrix classifies.
DIRECTORY_MANIFEST_VERSION = "1.0.0"

MECHANIZATIONS = ("structural", "coverage", "advisory", "out_of_scope")
STATUSES = ("active", "pending_directory_entry", "reference_only")


def _row(source, citation, tier, mechanization, frameworks_enum,
         routing_trigger, status="active", note=""):
    return {
        "source": source, "citation": citation, "tier": tier,
        "mechanization": mechanization, "frameworks_enum": frameworks_enum,
        "routing_trigger": routing_trigger, "status": status, "note": note,
    }


# --------------------------------------------------------------- tier 1
_TIER1 = (
    _row("ftc-act-section-5", "15 U.S.C. § 45", 1, "structural", "FTC",
         "always (universal deception/unfairness baseline)"),
    _row("ftc-endorsement-guides", "16 CFR Part 255", 1, "structural", "FTC",
         "endorsement_marker entity or endorsement claim present"),
    _row("ftc-consumer-reviews-rule", "16 CFR Part 465", 1, "structural", "FTC",
         "review/testimonial wording in claims"),
    _row("ftc-deceptive-pricing-guides", "16 CFR Part 233", 1, "structural", "FTC",
         "former-price/sale pricing claims"),
    _row("ftc-free-offer-guides", "16 CFR Part 251", 1, "structural", "FTC",
         "'free' offer wording in claims"),
    _row("ftc-telemarketing-sales-rule", "16 CFR Part 310", 1, "structural", "TCPA",
         "telemarketing CTA / consent language present",
         note="telemarketing family; routed with TCPA"),
    _row("ftc-can-spam-rule", "16 CFR Part 316", 1, "structural", "CAN-SPAM",
         "optout_marker entity present (email creative)"),
    _row("ftc-coppa", "16 CFR Part 312", 1, "coverage", "COPPA",
         "child-directed audience signals"),
    _row("cfpb-reg-z-tila", "12 CFR Part 1026 (advertising: §§ 1026.16, 1026.24)",
         1, "structural", "TILA",
         "credit product_type or apr/rate entity (trigger terms)"),
    _row("cfpb-reg-dd-tisa", "12 CFR Part 1030 (advertising: § 1030.8)",
         1, "structural", "Reg_DD",
         "deposit_account product_type or APY percentage"),
    _row("cfpb-reg-b-ecoa", "12 CFR Part 1002", 1, "structural", "ECOA",
         "credit product_type"),
    _row("cfpb-reg-m-leasing", "12 CFR Part 1013 (advertising: § 1013.7)",
         1, "structural", "Reg_M", "consumer-lease product/wording"),
    _row("cfpb-reg-n-map", "12 CFR Part 1014", 1, "structural", "Reg_N",
         "mortgage product_type"),
    _row("cfpb-udaap-statute",
         "12 U.S.C. §§ 5531, 5536 (Dodd-Frank §§ 1031, 1036)",
         1, "structural", "CFPB",
         "any consumer-finance product_type",
         note="UDAAP routes under the CFPB family value"),
    _row("fdic-part-328", "12 CFR Part 328", 1, "structural", "FDIC",
         "FDIC wording or bank deposit_account"),
    _row("ncua-part-740", "12 CFR Part 740", 1, "structural", "NCUA",
         "credit-union wording / NCUA insurance signage",
         note="same shape as FDIC 328 for credit unions"),
    _row("sec-marketing-rule", "17 CFR 275.206(4)-1", 1, "coverage", "SEC",
         "investment product_type (adviser advertising)"),
    _row("sec-rule-482", "17 CFR 230.482", 1, "coverage", "SEC",
         "fund/performance advertising"),
    _row("sec-ica-rule-34b-1", "17 CFR 270.34b-1", 1, "coverage", "SEC",
         "fund sales literature"),
    _row("finra-rule-2210", "FINRA Rule 2210", 1, "coverage", "FINRA",
         "investment/crypto product_type (member communications)"),
    _row("fcc-tcpa-rules", "47 CFR § 64.1200", 1, "structural", "TCPA",
         "consent language / call-or-text CTA present"),
    _row("hud-fair-housing-advertising", "24 CFR Part 100", 1, "structural",
         "FAIR_HOUSING", "mortgage/housing product_type"),
)

# --------------------------------------------------------------- tier 2
# One row per state UDAP source; all route via the STATE_UDAP umbrella +
# AssetRepresentation.target_jurisdictions (per schema.Framework docs).
_STATE_UDAP_SOURCES = (
    ('us-al-udap', 'Ala. Code § 8-19-1 et seq.'),
    ('us-ak-udap', 'Alaska Stat. § 45.50.471 et seq.'),
    ('us-az-udap', 'Ariz. Rev. Stat. §§ 44-1521 to 44-1534'),
    ('us-ar-udap', 'Ark. Code § 4-88-101 et seq.'),
    ('us-ca-udap', 'Cal. Bus. & Prof. Code §§ 17200 (UCL), 17500 (False '
                   'Advertising Law); Civ. Code § 1750 (CLRA)'),
    ('us-co-udap', 'Colo. Rev. Stat. § 6-1-101 et seq.'),
    ('us-ct-udap', 'Conn. Gen. Stat. § 42-110a et seq. (Chapter 735a)'),
    ('us-de-udap', '6 Del. C. § 2511 et seq. (Consumer Fraud Act); § 2531 '
                   'et seq. (Deceptive Trade Practices)'),
    ('us-dc-udap', 'D.C. Code § 28-3901 et seq.'),
    ('us-fl-udap', 'Fla. Stat. §§ 501.201–501.213'),
    ('us-ga-udap', 'O.C.G.A. § 10-1-390 et seq.'),
    ('us-hi-udap', 'Haw. Rev. Stat. § 480-2; ch. 481A'),
    ('us-id-udap', 'Idaho Code § 48-601 et seq.'),
    ('us-il-udap', '815 ILCS 505 (Consumer Fraud Act); 815 ILCS 510 (UDTPA)'),
    ('us-in-udap', 'Ind. Code § 24-5-0.5'),
    ('us-ia-udap', 'Iowa Code § 714.16; ch. 714H (private right)'),
    ('us-ks-udap', 'Kan. Stat. § 50-623 et seq.'),
    ('us-ky-udap', 'KRS § 367.110 et seq.'),
    ('us-la-udap', 'La. R.S. 51:1401 et seq.'),
    ('us-me-udap', '5 M.R.S. § 205-A et seq.'),
    ('us-md-udap', 'Md. Code, Com. Law § 13-101 et seq.'),
    ('us-ma-udap', 'Mass. Gen. Laws ch. 93A; AG regs 940 CMR 3.00 (general) '
                   '& 6.00 (retail advertising)'),
    ('us-mi-udap', 'Mich. Comp. Laws § 445.901 et seq.'),
    ('us-mn-udap', 'Minn. Stat. § 325F.68 et seq. (consumer fraud); '
                   '§ 325F.67 (false advertising); § 325D.44 (UDTPA)'),
    ('us-ms-udap', 'Miss. Code § 75-24-1 et seq.'),
    ('us-mo-udap', 'Mo. Rev. Stat. § 407.010 et seq.'),
    ('us-mt-udap', 'Mont. Code Ann. § 30-14-101 et seq.'),
    ('us-ne-udap', 'Neb. Rev. Stat. § 59-1601 et seq. (CPA); § 87-301 '
                   'et seq. (UDTPA)'),
    ('us-nv-udap', 'Nev. Rev. Stat. § 598.0903 et seq.'),
    ('us-nh-udap', 'N.H. Rev. Stat. ch. 358-A'),
    ('us-nj-udap', 'N.J. Stat. § 56:8-1 et seq.'),
    ('us-nm-udap', 'N.M. Stat. § 57-12-1 et seq.'),
    ('us-ny-udap', 'N.Y. Gen. Bus. Law §§ 349 (deceptive acts), 350 (false '
                   'advertising) — Art. 22-A'),
    ('us-nc-udap', 'N.C. Gen. Stat. § 75-1.1'),
    ('us-nd-udap', 'N.D. Cent. Code ch. 51-15'),
    ('us-oh-udap', 'Ohio Rev. Code § 1345.01 et seq.'),
    ('us-ok-udap', '15 O.S. § 751 et seq. (CPA); 78 O.S. § 51 et seq. (UDTPA)'),
    ('us-or-udap', 'ORS § 646.605 et seq.'),
    ('us-pa-udap', '73 P.S. § 201-1 et seq.'),
    ('us-ri-udap', 'R.I. Gen. Laws § 6-13.1-1 et seq.'),
    ('us-sc-udap', 'S.C. Code § 39-5-10 et seq.'),
    ('us-sd-udap', 'S.D. Codified Laws ch. 37-24'),
    ('us-tn-udap', 'Tenn. Code § 47-18-101 et seq.'),
    ('us-tx-udap', 'Tex. Bus. & Com. Code ch. 17, subch. E (§ 17.41 et seq.)'),
    ('us-ut-udap', 'Utah Code § 13-11-1 et seq. (CSPA); § 13-11a (Truth in '
                   'Advertising Act)'),
    ('us-vt-udap', '9 V.S.A. § 2451 et seq.'),
    ('us-va-udap', 'Va. Code § 59.1-196 et seq.'),
    ('us-wa-udap', 'RCW ch. 19.86'),
    ('us-wv-udap', 'W. Va. Code § 46A-6-101 et seq.'),
    ('us-wi-udap', 'Wis. Stat. § 100.18 (fraudulent representations)'),
    ('us-wy-udap', 'Wyo. Stat. § 40-12-101 et seq.'),
)

_TIER2 = tuple(
    _row(src, cit, 2, "structural", "STATE_UDAP",
         f"target_jurisdictions contains US-{src[3:5].upper()}")
    for src, cit in _STATE_UDAP_SOURCES
) + (
    _row("us-ca-dfpi-ccfpl",
         "Cal. Fin. Code § 90000 et seq. (CCFPL) + 10 CCR DFPI regulations",
         2, "coverage", "STATE_FINREG",
         "US-CA targeted + consumer-finance product_type"),
    _row("us-ny-dfs-crypto-ads",
         "23 NYCRR § 200.18 (BitLicense advertising & marketing)",
         2, "coverage", "STATE_FINREG",
         "US-NY targeted + crypto product_type"),
)

# --------------------------------------------------------------- tier 3
_TIER3 = (
    _row("ref-nclc-50-state-report",
         "NCLC, Consumer Protection in the States (50-state UDAP report)",
         3, "out_of_scope", None, "n/a", status="reference_only",
         note="secondary research reference verifying the state table; "
              "imposes no advertising obligation"),
    _row("ref-nclc-state-summaries",
         "NCLC, State-by-State Summaries of State UDAP Statutes (Appendix)",
         3, "out_of_scope", None, "n/a", status="reference_only",
         note="secondary research reference; no advertising obligation"),
    _row("ref-cozen-50-state-chart",
         "Jurisdictions Comparative Chart: Survey of Consumer Protection "
         "Statutes", 3, "out_of_scope", None, "n/a", status="reference_only",
         note="secondary research reference; no advertising obligation"),
    _row("ref-justia-50-state-survey",
         "Consumer Protection Laws: 50-State Survey", 3, "out_of_scope",
         None, "n/a", status="reference_only",
         note="secondary research reference; no advertising obligation"),
)

# ------------------------------------------- classified ahead of directory
# Framework families in the settled classification whose sources are not
# yet rows of directory manifest 1.0.0. Encoded now so enum + routing
# support exists the day the directory adds them.
_PENDING = (
    # -- structural --
    _row("dod-mla", "32 CFR Part 232 (36% MAPR cap + required disclosures)",
         1, "structural", "MLA", "covered-borrower credit advertising",
         status="pending_directory_entry"),
    _row("cfpb-reg-f-fdcpa", "12 CFR Part 1006 (FDCPA); 15 U.S.C. § 1692",
         1, "structural", "FDCPA", "debt-collection messaging",
         status="pending_directory_entry"),
    _row("fcra-prescreen-firm-offer",
         "15 U.S.C. § 1681m(d); 12 CFR Part 1022 (Reg V)",
         1, "structural", "FCRA",
         "prescreened/firm-offer-of-credit wording",
         status="pending_directory_entry"),
    _row("cfpb-reg-e-efta", "12 CFR Part 1005 (Reg E / EFTA)",
         1, "structural", "Reg_E", "EFT/overdraft service advertising",
         status="pending_directory_entry"),
    _row("wcag-contrast", "WCAG 2.x SC 1.4.3 (contrast minimum)",
         1, "structural", "WCAG",
         "always for image creatives (cv_findings.contrast_ratio already "
         "measures it)", status="pending_directory_entry"),
    # -- coverage --
    _row("cftc-nfa-promotional", "NFA Compliance Rule 2-29; 17 CFR § 4.41",
         1, "coverage", "CFTC_NFA", "commodity/futures/forex product",
         status="pending_directory_entry"),
    _row("glba-reg-p", "12 CFR Part 1016 (Reg P)", 1, "coverage", "GLBA",
         "financial product + data-sharing claims",
         status="pending_directory_entry"),
    _row("ftc-safeguards", "16 CFR Part 314 (Safeguards Rule)", 1,
         "coverage", "GLBA", "security claims by financial institutions",
         status="pending_directory_entry",
         note="GLBA family umbrella covers Reg P + Safeguards"),
    _row("scra", "50 U.S.C. § 3901 et seq.", 1, "coverage", "SCRA",
         "military-targeted credit advertising",
         status="pending_directory_entry"),
    _row("state-privacy",
         "Cal. Civ. Code § 1798.100 et seq. (CCPA/CPRA); Va. Code "
         "§ 59.1-575 et seq. (VCDPA); sister acts",
         2, "coverage", "STATE_PRIVACY",
         "state targeted + data-collection/personalization claims",
         status="pending_directory_entry",
         note="umbrella: individual states via target_jurisdictions"),
    _row("state-mini-tcpa",
         "Fla. Stat. § 501.059 (FTSA); Okla. 15 O.S. § 775C (mini-TCPAs)",
         2, "coverage", "MINI_TCPA",
         "state targeted + telemarketing/SMS CTA",
         status="pending_directory_entry",
         note="umbrella: individual states via target_jurisdictions"),
    _row("nmls-licensing-disclosure",
         "SAFE Act, 12 U.S.C. § 5101 et seq. (NMLS ID display)",
         2, "coverage", "NMLS", "mortgage lender/broker creative",
         status="pending_directory_entry"),
    _row("platform-policies",
         "Google Financial products & services policy; Meta financial ads "
         "policies", 3, "coverage", "PLATFORM_POLICY",
         "platform-destined creative", status="pending_directory_entry",
         note="umbrella: contractual, stricter-than-law gates"),
    _row("card-network-rules",
         "Visa Product Brand Standards; Mastercard Standards", 3,
         "coverage", "CARD_NETWORK", "card product using network marks",
         status="pending_directory_entry"),
    _row("self-regulatory",
         "NAD/CARU procedures; DAA Self-Regulatory Principles; NAI Code; "
         "IAB guidance", 3, "coverage", "SELF_REG",
         "behavioral-advertising or child-directed creative",
         status="pending_directory_entry",
         note="umbrella: industry self-regulation"),
    # -- advisory (process/governance; out of creative scope) --
    _row("sec-204-2-books-records", "17 CFR 275.204-2", 1, "advisory", "SEC",
         "SEC routed -> advisory flag", status="pending_directory_entry",
         note="adviser recordkeeping applies to the advertiser's program"),
    _row("finra-4511-17a-4", "FINRA Rule 4511; 17 CFR § 240.17a-4", 1,
         "advisory", "FINRA", "FINRA routed -> advisory flag",
         status="pending_directory_entry",
         note="books-and-records retention for member communications"),
    _row("cfpb-cms",
         "CFPB Supervision & Examination Manual — Compliance Management "
         "System", 1, "advisory", "CFPB", "CFPB routed -> advisory flag",
         status="pending_directory_entry",
         note="organizational compliance program expectation"),
    _row("pci-dss", "PCI DSS v4.0", 3, "advisory", "PCI_DSS",
         "always (advertiser-level payment-card program)",
         status="pending_directory_entry",
         note="process rule per directory architecture notes"),
    _row("nist-privacy-framework", "NIST Privacy Framework v1.0", 3,
         "advisory", "NIST_PRIVACY",
         "always (voluntary governance baseline)",
         status="pending_directory_entry",
         note="process rule per directory architecture notes"),
)

COVERAGE_MATRIX = _TIER1 + _TIER2 + _TIER3 + _PENDING


# ------------------------------------------------------------ derived views

def rows_for_mechanization(mech: str) -> tuple:
    return tuple(r for r in COVERAGE_MATRIX if r["mechanization"] == mech)


#: Advisory emission table: framework value that triggers the advisory ->
#: matrix rows to name. Rows whose trigger is "always ..." emit on every
#: run regardless of routing.
ADVISORY_ON_ROUTED = {}
ADVISORY_ALWAYS = []
for _r in rows_for_mechanization("advisory"):
    if _r["routing_trigger"].startswith("always"):
        ADVISORY_ALWAYS.append(_r)
    else:
        ADVISORY_ON_ROUTED.setdefault(_r["frameworks_enum"], []).append(_r)


def validate_matrix() -> None:
    """Invariants: unique sources, legal mechanization/status values, and
    every frameworks_enum value present in schema.Framework."""
    from schema import Framework

    seen = set()
    valid_fw = {f.value for f in Framework}
    for r in COVERAGE_MATRIX:
        if r["source"] in seen:
            raise ValueError(f"duplicate source {r['source']!r}")
        seen.add(r["source"])
        if r["mechanization"] not in MECHANIZATIONS:
            raise ValueError(f"{r['source']}: bad mechanization")
        if r["status"] not in STATUSES:
            raise ValueError(f"{r['source']}: bad status")
        if r["mechanization"] == "out_of_scope":
            if not r["note"]:
                raise ValueError(f"{r['source']}: out_of_scope needs a reason")
        elif r["frameworks_enum"] not in valid_fw:
            raise ValueError(
                f"{r['source']}: frameworks_enum {r['frameworks_enum']!r} "
                "not in schema.Framework")


def render_markdown() -> str:
    """docs/coverage_matrix.md content, generated from the constant."""
    by_mech = {m: len(rows_for_mechanization(m)) for m in MECHANIZATIONS}
    lines = [
        "# Regulatory Coverage Matrix",
        "",
        f"Generated from `rule_engine/coverage_matrix.py` "
        f"v{COVERAGE_MATRIX_VERSION} (directory manifest "
        f"{DIRECTORY_MANIFEST_VERSION}). **Do not edit by hand** — edit the "
        "constant and regenerate:",
        "",
        "```bash",
        "python -m rule_engine.coverage_matrix > docs/coverage_matrix.md",
        "```",
        "",
        "This table is hashed into `rule_engine.version.ruleset_hash`, so "
        "any reclassification changes the ruleset hash.",
        "",
        "## Mechanization key",
        "",
        "| mechanization | meaning |",
        "|---|---|",
        "| `structural` | deterministic checks on the creative are possible |",
        "| `coverage` | engine enforces that the LLM evaluated it when routed |",
        "| `advisory` | process/governance rule — engine emits a "
        "`CheckResult` with `scope=\"advisory\"` naming it as applicable to "
        "the advertiser but out of creative scope |",
        "| `out_of_scope` | not an advertising obligation; reason recorded |",
        "",
        f"Totals: {len(COVERAGE_MATRIX)} rows — "
        + ", ".join(f"{by_mech[m]} {m}" for m in MECHANIZATIONS) + ".",
        "",
        "## Matrix",
        "",
        "| source | citation | tier | mechanization | frameworks_enum | "
        "routing_trigger | status |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in COVERAGE_MATRIX:
        fw = r["frameworks_enum"] or "—"
        cit = r["citation"].replace("|", "\\|")
        trig = r["routing_trigger"].replace("|", "\\|")
        note = f" ⟨{r['note']}⟩" if r["note"] else ""
        lines.append(
            f"| {r['source']} | {cit} | {r['tier']} | {r['mechanization']} "
            f"| {fw} | {trig}{note} | {r['status']} |")
    lines += [
        "",
        "## Notes",
        "",
        "- `status=pending_directory_entry` rows encode the settled "
        "classification for framework families the directory manifest "
        f"{DIRECTORY_MANIFEST_VERSION} does not yet list as sources; they "
        "keep enum and routing support ahead of the directory update.",
        "- `out_of_scope` is used only for the tier-3 secondary research "
        "references (NCLC/Cozen/Justia surveys): they verify the state "
        "UDAP table but impose no advertising obligation themselves.",
        "- State UDAP rows route via the single `STATE_UDAP` umbrella "
        "value + `AssetRepresentation.target_jurisdictions`, per the "
        "schema.Framework convention.",
        "",
    ]
    return "\n".join(lines)


validate_matrix()


if __name__ == "__main__":
    print(render_markdown())
