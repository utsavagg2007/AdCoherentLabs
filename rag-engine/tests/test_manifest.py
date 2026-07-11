"""Manifest invariants against the real adcoherent_regulatory_sources.json."""

import pytest

from adcoherent_rag import config
from adcoherent_rag.manifest import (
    MANUAL_STUB_SOURCES,
    default_ingest_sources,
    frameworks_for,
    get_source,
    load_manifest,
    parse_cfr_citation,
    source_family,
)


def test_manifest_loads_all_sources():
    specs = load_manifest()
    assert len(specs) == 79
    assert len({s.id for s in specs}) == 79  # ids unique


def test_tier_counts():
    specs = load_manifest()
    assert sum(1 for s in specs if s.tier == 1) == 22
    assert sum(1 for s in specs if s.tier == 3) == 4


def test_default_ingest_selection():
    selected = default_ingest_sources()
    ids = {s.id for s in selected}
    # every tier-1 source
    assert all(s.id in ids for s in load_manifest() if s.tier == 1)
    # the 7 priority-state UDAP statutes
    for sid in ("us-ca-udap", "us-ny-udap", "us-tx-udap", "us-fl-udap",
                "us-il-udap", "us-ma-udap", "us-nj-udap"):
        assert sid in ids
    # priority-state finreg sources are selected (real strategies now)
    assert "us-ca-dfpi-ccfpl" in ids and "us-ny-dfs-crypto-ads" in ids
    # no tier-3 references, no non-priority states
    assert not any(get_source(sid).tier == 3 for sid in ids)
    assert "us-al-udap" not in ids and "us-wy-udap" not in ids
    assert len(selected) == 31


@pytest.mark.parametrize(
    "citation,expected",
    [
        ("12 CFR Part 1026 (advertising: §§ 1026.16, 1026.24)", (12, 1026, None)),
        ("17 CFR 275.206(4)-1", (17, 275, "206(4)-1")),
        ("17 CFR 230.482", (17, 230, "482")),
        ("47 CFR § 64.1200", (47, 64, "1200")),
        ("16 CFR Part 255", (16, 255, None)),
    ],
)
def test_parse_cfr_citation(citation, expected):
    assert parse_cfr_citation(citation) == expected


def test_source_families():
    assert source_family(get_source("cfpb-reg-dd-tisa")) == "cfr"
    assert source_family(get_source("ftc-act-section-5")) == "uscode_html"
    assert source_family(get_source("finra-rule-2210")) == "finra_html"
    assert source_family(get_source("us-tx-udap")) == "state_html"
    assert source_family(get_source("ref-nclc-50-state-report")) == "generic_pdf"
    # CCFPL graduated from manual stub to a real leginfo strategy
    assert source_family(get_source("us-ca-dfpi-ccfpl")) == "state_html"
    for sid in MANUAL_STUB_SOURCES:
        assert source_family(get_source(sid)) == "manual_stub"


def test_frameworks_line_up_with_nlp_routing():
    # the NLP layer emits routing.frameworks like ["Reg_DD", "FTC"]
    assert "Reg_DD" in frameworks_for(get_source("cfpb-reg-dd-tisa"))
    assert "FTC" in frameworks_for(get_source("ftc-endorsement-guides"))
    ca = frameworks_for(get_source("us-ca-udap"))
    assert "STATE_UDAP" in ca and "US-CA" in ca


def test_priority_states_config():
    assert config.PRIORITY_STATE_JURISDICTIONS == {
        "US-CA", "US-NY", "US-TX", "US-FL", "US-IL", "US-MA", "US-NJ",
    }
