"""Compiled state UDAP metadata for STATE_UDAP routing/checks.

Authored once (2026-07-10) from adcoherent_regulatory_sources.json
v1.0.0 (tier-2 state_udap entries) plus a curated exemption layer;
never fetched at runtime — the determinism guard (rule_engine/core.py)
applies. credit_exempt=True disables credit-ad state checks for that
state, so it is set ONLY for textbook broad regulated-industry
exemptions and every True entry appears on the VERIFY list below.
Uncertain states are conservatively credit_exempt=False with VERIFY
in notes: a wrongly-run check is cheap, a silently-disabled one is
not. Verification reference: NCLC 50-state UDAP report (tier-3,
ref-nclc-50-state-report) — a routing table, never citable legal text.
"""

from __future__ import annotations

STATE_TABLE_VERSION = "v1"

STATE_UDAP_TABLE: dict[str, dict] = {
    "US-AK": {
        "statute": "Alaska Stat. \u00a7 45.50.471 et seq.",
        "name": "Alaska Unfair Trade Practices and Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-AL": {
        "statute": "Ala. Code \u00a7 8-19-1 et seq.",
        "name": "Alabama Deceptive Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-AR": {
        "statute": "Ark. Code \u00a7 4-88-101 et seq.",
        "name": "Arkansas Deceptive Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-AZ": {
        "statute": "Ariz. Rev. Stat. \u00a7\u00a7 44-1521 to 44-1534",
        "name": "Arizona Consumer Fraud Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-CA": {
        "statute": "Cal. Bus. & Prof. Code \u00a7\u00a7 17200 (UCL), 17500 (False Advertising Law); Civ. Code \u00a7 1750 (CLRA)",
        "name": "California Unfair Competition Law + False Advertising Law + CLRA",
        "credit_exempt": False,
        "notes": "Credit fully covered: \u00a7 17500 is the operative false-advertising standard and \u00a7 17200 borrows violations of any other law; note CLRA (Civ. Code 1750) generally does not reach pure credit transactions.",
    },
    "US-CO": {
        "statute": "Colo. Rev. Stat. \u00a7 6-1-101 et seq.",
        "name": "Colorado Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-CT": {
        "statute": "Conn. Gen. Stat. \u00a7 42-110a et seq. (Chapter 735a)",
        "name": "Connecticut Unfair Trade Practices Act (CUTPA)",
        "credit_exempt": False,
        "notes": "CUTPA follows FTC Act interpretation and reaches consumer credit.",
    },
    "US-DC": {
        "statute": "D.C. Code \u00a7 28-3901 et seq.",
        "name": "DC Consumer Protection Procedures Act (CPPA)",
        "credit_exempt": False,
        "notes": "CPPA reach over credit expanded by amendment; confirm current credit coverage. Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-DE": {
        "statute": "6 Del. C. \u00a7 2511 et seq. (Consumer Fraud Act); \u00a7 2531 et seq. (Deceptive Trade Practices)",
        "name": "Delaware Consumer Fraud Act + UDTPA",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-FL": {
        "statute": "Fla. Stat. \u00a7\u00a7 501.201\u2013501.213",
        "name": "Florida Deceptive and Unfair Trade Practices Act (FDUTPA)",
        "credit_exempt": False,
        "notes": "FDUTPA \u00a7 501.212(4) exempts federally regulated banks/S&Ls; non-bank fintech lenders are covered. Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-GA": {
        "statute": "O.C.G.A. \u00a7 10-1-390 et seq.",
        "name": "Georgia Fair Business Practices Act",
        "credit_exempt": True,
        "notes": "FBPA exempts activities regulated by state/federal agencies (O.C.G.A. \u00a7 10-1-396); regulated lending is generally outside its scope. VERIFY: exemption disables state checks for this state \u2014 confirm before relying on it.",
    },
    "US-HI": {
        "statute": "Haw. Rev. Stat. \u00a7 480-2; ch. 481A",
        "name": "Hawaii Unfair or Deceptive Acts or Practices + UDTPA",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-IA": {
        "statute": "Iowa Code \u00a7 714.16; ch. 714H (private right)",
        "name": "Iowa Consumer Fraud Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-ID": {
        "statute": "Idaho Code \u00a7 48-601 et seq.",
        "name": "Idaho Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-IL": {
        "statute": "815 ILCS 505 (Consumer Fraud Act); 815 ILCS 510 (UDTPA)",
        "name": "Illinois Consumer Fraud and Deceptive Business Practices Act",
        "credit_exempt": False,
        "notes": "Consumer Fraud Act covers lending; active AG enforcement on fintech marketing.",
    },
    "US-IN": {
        "statute": "Ind. Code \u00a7 24-5-0.5",
        "name": "Indiana Deceptive Consumer Sales Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-KS": {
        "statute": "Kan. Stat. \u00a7 50-623 et seq.",
        "name": "Kansas Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-KY": {
        "statute": "KRS \u00a7 367.110 et seq.",
        "name": "Kentucky Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-LA": {
        "statute": "La. R.S. 51:1401 et seq.",
        "name": "Louisiana Unfair Trade Practices and Consumer Protection Law (LUTPA)",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-MA": {
        "statute": "Mass. Gen. Laws ch. 93A; AG regs 940 CMR 3.00 (general) & 6.00 (retail advertising)",
        "name": "Massachusetts Consumer Protection Act + AG Advertising Regulations",
        "credit_exempt": False,
        "notes": "Ch. 93A covers credit; AG advertising regs 940 CMR 3.00 and 6.00 add specific advertising rules.",
    },
    "US-MD": {
        "statute": "Md. Code, Com. Law \u00a7 13-101 et seq.",
        "name": "Maryland Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-ME": {
        "statute": "5 M.R.S. \u00a7 205-A et seq.",
        "name": "Maine Unfair Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-MI": {
        "statute": "Mich. Comp. Laws \u00a7 445.901 et seq.",
        "name": "Michigan Consumer Protection Act",
        "credit_exempt": True,
        "notes": "Broad 'transaction or conduct specifically authorized' exemption (MCL 445.904) as read by Smith v. Globe Life \u2014 most regulated lenders effectively outside the MCPA. VERIFY: exemption disables state checks for this state \u2014 confirm before relying on it.",
    },
    "US-MN": {
        "statute": "Minn. Stat. \u00a7 325F.68 et seq. (consumer fraud); \u00a7 325F.67 (false advertising); \u00a7 325D.44 (UDTPA)",
        "name": "Minnesota Prevention of Consumer Fraud Act + False Statement in Advertising Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-MO": {
        "statute": "Mo. Rev. Stat. \u00a7 407.010 et seq.",
        "name": "Missouri Merchandising Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-MS": {
        "statute": "Miss. Code \u00a7 75-24-1 et seq.",
        "name": "Mississippi Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-MT": {
        "statute": "Mont. Code Ann. \u00a7 30-14-101 et seq.",
        "name": "Montana Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NC": {
        "statute": "N.C. Gen. Stat. \u00a7 75-1.1",
        "name": "North Carolina Unfair and Deceptive Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-ND": {
        "statute": "N.D. Cent. Code ch. 51-15",
        "name": "North Dakota Unlawful Sales or Advertising Practices",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NE": {
        "statute": "Neb. Rev. Stat. \u00a7 59-1601 et seq. (CPA); \u00a7 87-301 et seq. (UDTPA)",
        "name": "Nebraska Consumer Protection Act + UDTPA",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NH": {
        "statute": "N.H. Rev. Stat. ch. 358-A",
        "name": "New Hampshire Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NJ": {
        "statute": "N.J. Stat. \u00a7 56:8-1 et seq.",
        "name": "New Jersey Consumer Fraud Act",
        "credit_exempt": False,
        "notes": "CFA covers credit; among the strongest and most heavily litigated state UDAP statutes.",
    },
    "US-NM": {
        "statute": "N.M. Stat. \u00a7 57-12-1 et seq.",
        "name": "New Mexico Unfair Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NV": {
        "statute": "Nev. Rev. Stat. \u00a7 598.0903 et seq.",
        "name": "Nevada Deceptive Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-NY": {
        "statute": "N.Y. Gen. Bus. Law \u00a7\u00a7 349 (deceptive acts), 350 (false advertising) \u2014 Art. 22-A",
        "name": "New York Deceptive Practices + False Advertising Law",
        "credit_exempt": False,
        "notes": "GBL \u00a7\u00a7 349/350 cover credit; \u00a7 350 is the most-cited state false-advertising provision in fintech litigation.",
    },
    "US-OH": {
        "statute": "Ohio Rev. Code \u00a7 1345.01 et seq.",
        "name": "Ohio Consumer Sales Practices Act",
        "credit_exempt": True,
        "notes": "CSPA 'consumer transaction' excludes dealings with financial institutions (ORC 1345.01(A)); 2007 amendments re-covered some non-bank mortgage conduct. VERIFY: exemption disables state checks for this state \u2014 confirm before relying on it.",
    },
    "US-OK": {
        "statute": "15 O.S. \u00a7 751 et seq. (CPA); 78 O.S. \u00a7 51 et seq. (UDTPA)",
        "name": "Oklahoma Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-OR": {
        "statute": "ORS \u00a7 646.605 et seq.",
        "name": "Oregon Unlawful Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-PA": {
        "statute": "73 P.S. \u00a7 201-1 et seq.",
        "name": "Pennsylvania Unfair Trade Practices and Consumer Protection Law (UTPCPL)",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-RI": {
        "statute": "R.I. Gen. Laws \u00a7 6-13.1-1 et seq.",
        "name": "Rhode Island Deceptive Trade Practices Act",
        "credit_exempt": True,
        "notes": "Exempts activities subject to monitoring by state/federal regulatory bodies (\u00a7 6-13.1-4), broadly read to cover banks and licensed lenders. VERIFY: exemption disables state checks for this state \u2014 confirm before relying on it.",
    },
    "US-SC": {
        "statute": "S.C. Code \u00a7 39-5-10 et seq.",
        "name": "South Carolina Unfair Trade Practices Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-SD": {
        "statute": "S.D. Codified Laws ch. 37-24",
        "name": "South Dakota Deceptive Trade Practices and Consumer Protection",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-TN": {
        "statute": "Tenn. Code \u00a7 47-18-101 et seq.",
        "name": "Tennessee Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-TX": {
        "statute": "Tex. Bus. & Com. Code ch. 17, subch. E (\u00a7 17.41 et seq.)",
        "name": "Texas Deceptive Trade Practices\u2013Consumer Protection Act (DTPA)",
        "credit_exempt": False,
        "notes": "Money/credit is generally not 'goods or services' under the DTPA (La Sara Grain); credit tied to goods/services purchases is covered. Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-UT": {
        "statute": "Utah Code \u00a7 13-11-1 et seq. (CSPA); \u00a7 13-11a (Truth in Advertising Act)",
        "name": "Utah Consumer Sales Practices Act + Truth in Advertising Act",
        "credit_exempt": False,
        "notes": "Utah also has an explicit Truth in Advertising Act (\u00a7 13-11a) \u2014 rare among states; worth its own rule set. Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-VA": {
        "statute": "Va. Code \u00a7 59.1-196 et seq.",
        "name": "Virginia Consumer Protection Act",
        "credit_exempt": True,
        "notes": "VCPA exempts banks, savings institutions, credit unions, and licensed lenders (\u00a7 59.1-199(D)). VERIFY: exemption disables state checks for this state \u2014 confirm before relying on it.",
    },
    "US-VT": {
        "statute": "9 V.S.A. \u00a7 2451 et seq.",
        "name": "Vermont Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-WA": {
        "statute": "RCW ch. 19.86",
        "name": "Washington Consumer Protection Act",
        "credit_exempt": False,
        "notes": "RCW 19.86 covers credit; per-se violations via other consumer statutes.",
    },
    "US-WI": {
        "statute": "Wis. Stat. \u00a7 100.18 (fraudulent representations)",
        "name": "Wisconsin Deceptive Trade Practices Act",
        "credit_exempt": False,
        "notes": "\u00a7 100.18 targets fraudulent representations in advertising specifically. Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-WV": {
        "statute": "W. Va. Code \u00a7 46A-6-101 et seq.",
        "name": "West Virginia Consumer Credit and Protection Act (Art. 6)",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
    "US-WY": {
        "statute": "Wyo. Stat. \u00a7 40-12-101 et seq.",
        "name": "Wyoming Consumer Protection Act",
        "credit_exempt": False,
        "notes": "Exemption status unverified \u2014 VERIFY against NCLC 50-state UDAP report (ref-nclc-50-state-report).",
    },
}


if __name__ == "__main__":
    n_exempt = sum(1 for v in STATE_UDAP_TABLE.values()
                   if v["credit_exempt"])
    n_verify = sum(1 for v in STATE_UDAP_TABLE.values()
                   if "VERIFY" in v["notes"])
    print(f"{len(STATE_UDAP_TABLE)} jurisdictions | "
          f"{n_exempt} credit_exempt=True | {n_verify} on VERIFY list")
    for j, v in STATE_UDAP_TABLE.items():
        if "VERIFY" in v["notes"]:
            tag = "True " if v["credit_exempt"] else "False"
            print(f"  VERIFY {j} (credit_exempt={tag}): {v['statute']}")


# ## VERIFY list — confirm against the NCLC 50-state UDAP report
# (tier-3 ref-nclc-50-state-report) before state checks ship.
# credit_exempt=True entries matter most: True silently disables
# checks for that state.
#
#   US-AK: credit_exempt=False set conservatively — confirm no exemption
#   US-AL: credit_exempt=False set conservatively — confirm no exemption
#   US-AR: credit_exempt=False set conservatively — confirm no exemption
#   US-AZ: credit_exempt=False set conservatively — confirm no exemption
#   US-CO: credit_exempt=False set conservatively — confirm no exemption
#   US-DC: credit_exempt=False set conservatively — confirm no exemption
#   US-DE: credit_exempt=False set conservatively — confirm no exemption
#   US-FL: credit_exempt=False set conservatively — confirm no exemption
#   US-GA: credit_exempt=True — confirm the exemption
#   US-HI: credit_exempt=False set conservatively — confirm no exemption
#   US-IA: credit_exempt=False set conservatively — confirm no exemption
#   US-ID: credit_exempt=False set conservatively — confirm no exemption
#   US-IN: credit_exempt=False set conservatively — confirm no exemption
#   US-KS: credit_exempt=False set conservatively — confirm no exemption
#   US-KY: credit_exempt=False set conservatively — confirm no exemption
#   US-LA: credit_exempt=False set conservatively — confirm no exemption
#   US-MD: credit_exempt=False set conservatively — confirm no exemption
#   US-ME: credit_exempt=False set conservatively — confirm no exemption
#   US-MI: credit_exempt=True — confirm the exemption
#   US-MN: credit_exempt=False set conservatively — confirm no exemption
#   US-MO: credit_exempt=False set conservatively — confirm no exemption
#   US-MS: credit_exempt=False set conservatively — confirm no exemption
#   US-MT: credit_exempt=False set conservatively — confirm no exemption
#   US-NC: credit_exempt=False set conservatively — confirm no exemption
#   US-ND: credit_exempt=False set conservatively — confirm no exemption
#   US-NE: credit_exempt=False set conservatively — confirm no exemption
#   US-NH: credit_exempt=False set conservatively — confirm no exemption
#   US-NM: credit_exempt=False set conservatively — confirm no exemption
#   US-NV: credit_exempt=False set conservatively — confirm no exemption
#   US-OH: credit_exempt=True — confirm the exemption
#   US-OK: credit_exempt=False set conservatively — confirm no exemption
#   US-OR: credit_exempt=False set conservatively — confirm no exemption
#   US-PA: credit_exempt=False set conservatively — confirm no exemption
#   US-RI: credit_exempt=True — confirm the exemption
#   US-SC: credit_exempt=False set conservatively — confirm no exemption
#   US-SD: credit_exempt=False set conservatively — confirm no exemption
#   US-TN: credit_exempt=False set conservatively — confirm no exemption
#   US-TX: credit_exempt=False set conservatively — confirm no exemption
#   US-UT: credit_exempt=False set conservatively — confirm no exemption
#   US-VA: credit_exempt=True — confirm the exemption
#   US-VT: credit_exempt=False set conservatively — confirm no exemption
#   US-WI: credit_exempt=False set conservatively — confirm no exemption
#   US-WV: credit_exempt=False set conservatively — confirm no exemption
#   US-WY: credit_exempt=False set conservatively — confirm no exemption
