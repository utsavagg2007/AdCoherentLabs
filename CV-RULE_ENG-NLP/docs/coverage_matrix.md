# Regulatory Coverage Matrix

Generated from `rule_engine/coverage_matrix.py` v1.0.0 (directory manifest 1.0.0). **Do not edit by hand** — edit the constant and regenerate:

```bash
python -m rule_engine.coverage_matrix > docs/coverage_matrix.md
```

This table is hashed into `rule_engine.version.ruleset_hash`, so any reclassification changes the ruleset hash.

## Mechanization key

| mechanization | meaning |
|---|---|
| `structural` | deterministic checks on the creative are possible |
| `coverage` | engine enforces that the LLM evaluated it when routed |
| `advisory` | process/governance rule — engine emits a `CheckResult` with `scope="advisory"` naming it as applicable to the advertiser but out of creative scope |
| `out_of_scope` | not an advertising obligation; reason recorded |

Totals: 99 rows — 73 structural, 17 coverage, 5 advisory, 4 out_of_scope.

## Matrix

| source | citation | tier | mechanization | frameworks_enum | routing_trigger | status |
|---|---|---|---|---|---|---|
| ftc-act-section-5 | 15 U.S.C. § 45 | 1 | structural | FTC | always (universal deception/unfairness baseline) | active |
| ftc-endorsement-guides | 16 CFR Part 255 | 1 | structural | FTC | endorsement_marker entity or endorsement claim present | active |
| ftc-consumer-reviews-rule | 16 CFR Part 465 | 1 | structural | FTC | review/testimonial wording in claims | active |
| ftc-deceptive-pricing-guides | 16 CFR Part 233 | 1 | structural | FTC | former-price/sale pricing claims | active |
| ftc-free-offer-guides | 16 CFR Part 251 | 1 | structural | FTC | 'free' offer wording in claims | active |
| ftc-telemarketing-sales-rule | 16 CFR Part 310 | 1 | structural | TCPA | telemarketing CTA / consent language present ⟨telemarketing family; routed with TCPA⟩ | active |
| ftc-can-spam-rule | 16 CFR Part 316 | 1 | structural | CAN-SPAM | optout_marker entity present (email creative) | active |
| ftc-coppa | 16 CFR Part 312 | 1 | coverage | COPPA | child-directed audience signals | active |
| cfpb-reg-z-tila | 12 CFR Part 1026 (advertising: §§ 1026.16, 1026.24) | 1 | structural | TILA | credit product_type or apr/rate entity (trigger terms) | active |
| cfpb-reg-dd-tisa | 12 CFR Part 1030 (advertising: § 1030.8) | 1 | structural | Reg_DD | deposit_account product_type or APY percentage | active |
| cfpb-reg-b-ecoa | 12 CFR Part 1002 | 1 | structural | ECOA | credit product_type | active |
| cfpb-reg-m-leasing | 12 CFR Part 1013 (advertising: § 1013.7) | 1 | structural | Reg_M | consumer-lease product/wording | active |
| cfpb-reg-n-map | 12 CFR Part 1014 | 1 | structural | Reg_N | mortgage product_type | active |
| cfpb-udaap-statute | 12 U.S.C. §§ 5531, 5536 (Dodd-Frank §§ 1031, 1036) | 1 | structural | CFPB | any consumer-finance product_type ⟨UDAAP routes under the CFPB family value⟩ | active |
| fdic-part-328 | 12 CFR Part 328 | 1 | structural | FDIC | FDIC wording or bank deposit_account | active |
| ncua-part-740 | 12 CFR Part 740 | 1 | structural | NCUA | credit-union wording / NCUA insurance signage ⟨same shape as FDIC 328 for credit unions⟩ | active |
| sec-marketing-rule | 17 CFR 275.206(4)-1 | 1 | coverage | SEC | investment product_type (adviser advertising) | active |
| sec-rule-482 | 17 CFR 230.482 | 1 | coverage | SEC | fund/performance advertising | active |
| sec-ica-rule-34b-1 | 17 CFR 270.34b-1 | 1 | coverage | SEC | fund sales literature | active |
| finra-rule-2210 | FINRA Rule 2210 | 1 | coverage | FINRA | investment/crypto product_type (member communications) | active |
| fcc-tcpa-rules | 47 CFR § 64.1200 | 1 | structural | TCPA | consent language / call-or-text CTA present | active |
| hud-fair-housing-advertising | 24 CFR Part 100 | 1 | structural | FAIR_HOUSING | mortgage/housing product_type | active |
| us-al-udap | Ala. Code § 8-19-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-AL | active |
| us-ak-udap | Alaska Stat. § 45.50.471 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-AK | active |
| us-az-udap | Ariz. Rev. Stat. §§ 44-1521 to 44-1534 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-AZ | active |
| us-ar-udap | Ark. Code § 4-88-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-AR | active |
| us-ca-udap | Cal. Bus. & Prof. Code §§ 17200 (UCL), 17500 (False Advertising Law); Civ. Code § 1750 (CLRA) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-CA | active |
| us-co-udap | Colo. Rev. Stat. § 6-1-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-CO | active |
| us-ct-udap | Conn. Gen. Stat. § 42-110a et seq. (Chapter 735a) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-CT | active |
| us-de-udap | 6 Del. C. § 2511 et seq. (Consumer Fraud Act); § 2531 et seq. (Deceptive Trade Practices) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-DE | active |
| us-dc-udap | D.C. Code § 28-3901 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-DC | active |
| us-fl-udap | Fla. Stat. §§ 501.201–501.213 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-FL | active |
| us-ga-udap | O.C.G.A. § 10-1-390 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-GA | active |
| us-hi-udap | Haw. Rev. Stat. § 480-2; ch. 481A | 2 | structural | STATE_UDAP | target_jurisdictions contains US-HI | active |
| us-id-udap | Idaho Code § 48-601 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-ID | active |
| us-il-udap | 815 ILCS 505 (Consumer Fraud Act); 815 ILCS 510 (UDTPA) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-IL | active |
| us-in-udap | Ind. Code § 24-5-0.5 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-IN | active |
| us-ia-udap | Iowa Code § 714.16; ch. 714H (private right) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-IA | active |
| us-ks-udap | Kan. Stat. § 50-623 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-KS | active |
| us-ky-udap | KRS § 367.110 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-KY | active |
| us-la-udap | La. R.S. 51:1401 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-LA | active |
| us-me-udap | 5 M.R.S. § 205-A et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-ME | active |
| us-md-udap | Md. Code, Com. Law § 13-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MD | active |
| us-ma-udap | Mass. Gen. Laws ch. 93A; AG regs 940 CMR 3.00 (general) & 6.00 (retail advertising) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MA | active |
| us-mi-udap | Mich. Comp. Laws § 445.901 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MI | active |
| us-mn-udap | Minn. Stat. § 325F.68 et seq. (consumer fraud); § 325F.67 (false advertising); § 325D.44 (UDTPA) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MN | active |
| us-ms-udap | Miss. Code § 75-24-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MS | active |
| us-mo-udap | Mo. Rev. Stat. § 407.010 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MO | active |
| us-mt-udap | Mont. Code Ann. § 30-14-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-MT | active |
| us-ne-udap | Neb. Rev. Stat. § 59-1601 et seq. (CPA); § 87-301 et seq. (UDTPA) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NE | active |
| us-nv-udap | Nev. Rev. Stat. § 598.0903 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NV | active |
| us-nh-udap | N.H. Rev. Stat. ch. 358-A | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NH | active |
| us-nj-udap | N.J. Stat. § 56:8-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NJ | active |
| us-nm-udap | N.M. Stat. § 57-12-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NM | active |
| us-ny-udap | N.Y. Gen. Bus. Law §§ 349 (deceptive acts), 350 (false advertising) — Art. 22-A | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NY | active |
| us-nc-udap | N.C. Gen. Stat. § 75-1.1 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-NC | active |
| us-nd-udap | N.D. Cent. Code ch. 51-15 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-ND | active |
| us-oh-udap | Ohio Rev. Code § 1345.01 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-OH | active |
| us-ok-udap | 15 O.S. § 751 et seq. (CPA); 78 O.S. § 51 et seq. (UDTPA) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-OK | active |
| us-or-udap | ORS § 646.605 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-OR | active |
| us-pa-udap | 73 P.S. § 201-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-PA | active |
| us-ri-udap | R.I. Gen. Laws § 6-13.1-1 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-RI | active |
| us-sc-udap | S.C. Code § 39-5-10 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-SC | active |
| us-sd-udap | S.D. Codified Laws ch. 37-24 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-SD | active |
| us-tn-udap | Tenn. Code § 47-18-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-TN | active |
| us-tx-udap | Tex. Bus. & Com. Code ch. 17, subch. E (§ 17.41 et seq.) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-TX | active |
| us-ut-udap | Utah Code § 13-11-1 et seq. (CSPA); § 13-11a (Truth in Advertising Act) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-UT | active |
| us-vt-udap | 9 V.S.A. § 2451 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-VT | active |
| us-va-udap | Va. Code § 59.1-196 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-VA | active |
| us-wa-udap | RCW ch. 19.86 | 2 | structural | STATE_UDAP | target_jurisdictions contains US-WA | active |
| us-wv-udap | W. Va. Code § 46A-6-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-WV | active |
| us-wi-udap | Wis. Stat. § 100.18 (fraudulent representations) | 2 | structural | STATE_UDAP | target_jurisdictions contains US-WI | active |
| us-wy-udap | Wyo. Stat. § 40-12-101 et seq. | 2 | structural | STATE_UDAP | target_jurisdictions contains US-WY | active |
| us-ca-dfpi-ccfpl | Cal. Fin. Code § 90000 et seq. (CCFPL) + 10 CCR DFPI regulations | 2 | coverage | STATE_FINREG | US-CA targeted + consumer-finance product_type | active |
| us-ny-dfs-crypto-ads | 23 NYCRR § 200.18 (BitLicense advertising & marketing) | 2 | coverage | STATE_FINREG | US-NY targeted + crypto product_type | active |
| ref-nclc-50-state-report | NCLC, Consumer Protection in the States (50-state UDAP report) | 3 | out_of_scope | — | n/a ⟨secondary research reference verifying the state table; imposes no advertising obligation⟩ | reference_only |
| ref-nclc-state-summaries | NCLC, State-by-State Summaries of State UDAP Statutes (Appendix) | 3 | out_of_scope | — | n/a ⟨secondary research reference; no advertising obligation⟩ | reference_only |
| ref-cozen-50-state-chart | Jurisdictions Comparative Chart: Survey of Consumer Protection Statutes | 3 | out_of_scope | — | n/a ⟨secondary research reference; no advertising obligation⟩ | reference_only |
| ref-justia-50-state-survey | Consumer Protection Laws: 50-State Survey | 3 | out_of_scope | — | n/a ⟨secondary research reference; no advertising obligation⟩ | reference_only |
| dod-mla | 32 CFR Part 232 (36% MAPR cap + required disclosures) | 1 | structural | MLA | covered-borrower credit advertising | pending_directory_entry |
| cfpb-reg-f-fdcpa | 12 CFR Part 1006 (FDCPA); 15 U.S.C. § 1692 | 1 | structural | FDCPA | debt-collection messaging | pending_directory_entry |
| fcra-prescreen-firm-offer | 15 U.S.C. § 1681m(d); 12 CFR Part 1022 (Reg V) | 1 | structural | FCRA | prescreened/firm-offer-of-credit wording | pending_directory_entry |
| cfpb-reg-e-efta | 12 CFR Part 1005 (Reg E / EFTA) | 1 | structural | Reg_E | EFT/overdraft service advertising | pending_directory_entry |
| wcag-contrast | WCAG 2.x SC 1.4.3 (contrast minimum) | 1 | structural | WCAG | always for image creatives (cv_findings.contrast_ratio already measures it) | pending_directory_entry |
| cftc-nfa-promotional | NFA Compliance Rule 2-29; 17 CFR § 4.41 | 1 | coverage | CFTC_NFA | commodity/futures/forex product | pending_directory_entry |
| glba-reg-p | 12 CFR Part 1016 (Reg P) | 1 | coverage | GLBA | financial product + data-sharing claims | pending_directory_entry |
| ftc-safeguards | 16 CFR Part 314 (Safeguards Rule) | 1 | coverage | GLBA | security claims by financial institutions ⟨GLBA family umbrella covers Reg P + Safeguards⟩ | pending_directory_entry |
| scra | 50 U.S.C. § 3901 et seq. | 1 | coverage | SCRA | military-targeted credit advertising | pending_directory_entry |
| state-privacy | Cal. Civ. Code § 1798.100 et seq. (CCPA/CPRA); Va. Code § 59.1-575 et seq. (VCDPA); sister acts | 2 | coverage | STATE_PRIVACY | state targeted + data-collection/personalization claims ⟨umbrella: individual states via target_jurisdictions⟩ | pending_directory_entry |
| state-mini-tcpa | Fla. Stat. § 501.059 (FTSA); Okla. 15 O.S. § 775C (mini-TCPAs) | 2 | coverage | MINI_TCPA | state targeted + telemarketing/SMS CTA ⟨umbrella: individual states via target_jurisdictions⟩ | pending_directory_entry |
| nmls-licensing-disclosure | SAFE Act, 12 U.S.C. § 5101 et seq. (NMLS ID display) | 2 | coverage | NMLS | mortgage lender/broker creative | pending_directory_entry |
| platform-policies | Google Financial products & services policy; Meta financial ads policies | 3 | coverage | PLATFORM_POLICY | platform-destined creative ⟨umbrella: contractual, stricter-than-law gates⟩ | pending_directory_entry |
| card-network-rules | Visa Product Brand Standards; Mastercard Standards | 3 | coverage | CARD_NETWORK | card product using network marks | pending_directory_entry |
| self-regulatory | NAD/CARU procedures; DAA Self-Regulatory Principles; NAI Code; IAB guidance | 3 | coverage | SELF_REG | behavioral-advertising or child-directed creative ⟨umbrella: industry self-regulation⟩ | pending_directory_entry |
| sec-204-2-books-records | 17 CFR 275.204-2 | 1 | advisory | SEC | SEC routed -> advisory flag ⟨adviser recordkeeping applies to the advertiser's program⟩ | pending_directory_entry |
| finra-4511-17a-4 | FINRA Rule 4511; 17 CFR § 240.17a-4 | 1 | advisory | FINRA | FINRA routed -> advisory flag ⟨books-and-records retention for member communications⟩ | pending_directory_entry |
| cfpb-cms | CFPB Supervision & Examination Manual — Compliance Management System | 1 | advisory | CFPB | CFPB routed -> advisory flag ⟨organizational compliance program expectation⟩ | pending_directory_entry |
| pci-dss | PCI DSS v4.0 | 3 | advisory | PCI_DSS | always (advertiser-level payment-card program) ⟨process rule per directory architecture notes⟩ | pending_directory_entry |
| nist-privacy-framework | NIST Privacy Framework v1.0 | 3 | advisory | NIST_PRIVACY | always (voluntary governance baseline) ⟨process rule per directory architecture notes⟩ | pending_directory_entry |

## Notes

- `status=pending_directory_entry` rows encode the settled classification for framework families the directory manifest 1.0.0 does not yet list as sources; they keep enum and routing support ahead of the directory update.
- `out_of_scope` is used only for the tier-3 secondary research references (NCLC/Cozen/Justia surveys): they verify the state UDAP table but impose no advertising obligation themselves.
- State UDAP rows route via the single `STATE_UDAP` umbrella value + `AssetRepresentation.target_jurisdictions`, per the schema.Framework convention.

