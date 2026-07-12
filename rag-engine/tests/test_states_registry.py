"""Offline invariants for the all-states fetch registry + chapter splitting."""

from __future__ import annotations

import pytest

from adcoherent_rag.fetch.states import (
    _CUSTOM_FETCHERS,
    IMPLEMENTED_JURISDICTIONS,
    STATE_STRATEGIES,
    StateStrategy,
)
from adcoherent_rag.manifest import load_manifest, source_family
from adcoherent_rag.models import FetchResult, SourceSpec
from adcoherent_rag.normalize.statute_html import (
    CHAPTER_SPLITS,
    StateHtmlNormalizer,
    split_chapter,
)


# ---------------------------------------------------------------------------
# Registry coverage / integrity


def test_every_state_source_has_a_fetch_path():
    """No state_udap/state_finreg source may fall through to 'no scraper'.

    Sources without a scrapeable official site must be manual stubs (family
    'manual_stub'), which source_family() already excludes from state_html.
    """
    uncovered = [
        s.id
        for s in load_manifest()
        if source_family(s) == "state_html"
        and s.id not in _CUSTOM_FETCHERS
        and s.id not in STATE_STRATEGIES
    ]
    assert uncovered == []


def test_all_51_jurisdictions_covered():
    """Every jurisdiction is either implemented or an explicit manual stub."""
    from adcoherent_rag.manifest import MANUAL_STUB_SOURCES

    specs = [
        s for s in load_manifest()
        if s.category in ("state_udap", "state_finreg")
    ]
    manifest_jurisdictions = {s.jurisdiction for s in specs}
    assert len(manifest_jurisdictions) == 51  # 50 states + DC

    stub_only = {
        j for j in manifest_jurisdictions
        if all(s.id in MANUAL_STUB_SOURCES for s in specs if s.jurisdiction == j)
    }
    assert manifest_jurisdictions <= (IMPLEMENTED_JURISDICTIONS | stub_only)
    # every stub has a documented reason
    for sid, reason in MANUAL_STUB_SOURCES.items():
        assert isinstance(reason, str) and len(reason) > 20, sid


def test_strategies_are_well_formed():
    for source_id, strategies in STATE_STRATEGIES.items():
        assert strategies, source_id
        for st in strategies:
            assert st.mode in {"sections", "chapter_html", "chapter_pdf", "linked_sections"}
            if st.mode == "sections":
                assert st.pages, source_id
                for url, hint, citation in st.pages:
                    assert url.startswith("http"), (source_id, url)
                    assert hint and citation, (source_id, url)
            elif st.mode in ("chapter_html", "chapter_pdf"):
                assert st.url and st.url.startswith("http"), source_id
                assert st.split in CHAPTER_SPLITS, (source_id, st.split)
            elif st.mode == "linked_sections":
                assert st.url and st.link_text_re, source_id


def test_chapter_split_configs_have_one_capture_group():
    for key, cfg in CHAPTER_SPLITS.items():
        assert cfg.marker.groups == 1, key
        assert "{num}" in cfg.key_template, key
        assert "{num}" in cfg.citation_template, key


def test_finreg_sources_do_not_collide_with_udap_fetchers():
    # us-ca-dfpi-ccfpl shares jurisdiction US-CA with us-ca-udap but must
    # resolve through its own registry entry, never the CA UDAP fetcher.
    assert "us-ca-dfpi-ccfpl" in STATE_STRATEGIES
    assert "us-ca-dfpi-ccfpl" not in _CUSTOM_FETCHERS
    ccfpl = STATE_STRATEGIES["us-ca-dfpi-ccfpl"][0]
    assert all("lawCode=FIN" in url for url, _, _ in ccfpl.pages)
    # NYDFS Part 200 text is Westlaw-only -> explicit manual stub, not a
    # strategy that would scrape viewer chrome.
    from adcoherent_rag.manifest import MANUAL_STUB_SOURCES

    assert "us-ny-dfs-crypto-ads" in MANUAL_STUB_SOURCES
    assert "us-ny-dfs-crypto-ads" not in STATE_STRATEGIES


def test_mirror_strategies_are_marked():
    for source_id, strategies in STATE_STRATEGIES.items():
        for st in strategies:
            urls = [u for u, _, _ in st.pages] + ([st.url] if st.url else [])
            for url in urls:
                if "justia.com" in url:
                    assert st.mirror == "justia", (source_id, url)


# ---------------------------------------------------------------------------
# Chapter splitting on synthetic fixtures


def _split(spec: SourceSpec, text: str, key: str):
    return split_chapter(spec, text, CHAPTER_SPLITS[key])


def test_ct_chapter_split_with_toc_dedup(make_spec):
    spec = make_spec(id="us-ct-udap", jurisdiction="US-CT")
    text = (
        # table-of-contents lines (short bodies -> must lose to real text)
        "Sec. 42-110a. Definitions.\n"
        "Sec. 42-110b. Unfair trade practices prohibited.\n"
        "Sec. 42-110a. Definitions. As used in this chapter: (1) "
        "“Commissioner” means the Commissioner of Consumer Protection "
        "of the state of Connecticut acting directly or through authorized agents.\n"
        "Sec. 42-110b. Unfair trade practices prohibited. (a) No person shall "
        "engage in unfair methods of competition and unfair or deceptive acts "
        "or practices in the conduct of any trade or commerce within this state.\n"
    )
    units = _split(spec, text, "ct-42-110")
    assert [u.section_key for u in units] == ["us-ct/gs/42-110a", "us-ct/gs/42-110b"]
    assert units[0].citation == "Conn. Gen. Stat. § 42-110a"
    assert "Commissioner of Consumer Protection" in units[0].text
    assert "unfair methods of competition" in units[1].text


def test_nv_nrs_chapter_split(make_spec):
    spec = make_spec(id="us-nv-udap", jurisdiction="US-NV")
    text = (
        "NRS 598.0915  “Deceptive trade practice” defined. A person "
        "engages in a deceptive trade practice if, in the course of business, "
        "the person knowingly makes a false representation as to the source of goods.\n"
        "NRS 598.0923  Further practices. A person engages in a deceptive trade "
        "practice when in the course of business the person conducts business "
        "without all required state, county or city licenses as required by law.\n"
    )
    units = _split(spec, text, "nv-nrs-598")
    assert [u.section_key for u in units] == ["us-nv/nrs/598.0915", "us-nv/nrs/598.0923"]
    assert units[0].citation == "Nev. Rev. Stat. § 598.0915"


def test_sc_and_nh_and_or_markers(make_spec):
    sc = make_spec(id="us-sc-udap", jurisdiction="US-SC")
    units = _split(
        sc,
        "SECTION 39-5-20. Unfair competition. (a) Unfair methods of competition "
        "and unfair or deceptive acts or practices in the conduct of any trade or "
        "commerce are hereby declared unlawful under South Carolina law today.\n"
        "SECTION 39-5-140. Actions. Any person who suffers any ascertainable loss "
        "of money or property as a result of a violation may bring an action to "
        "recover actual damages under this section of the South Carolina code.\n",
        "sc-39-5",
    )
    assert [u.section_key for u in units] == ["us-sc/code/39-5-20", "us-sc/code/39-5-140"]

    nh = make_spec(id="us-nh-udap", jurisdiction="US-NH")
    units = _split(
        nh,
        "358-A:1 Definitions. – In this chapter: I. “Documentary "
        "material” means the original or copy of a book, record, report, "
        "memorandum, paper, communication, tabulation, map, chart, or photograph.\n"
        "358-A:2 Acts Unlawful. – It shall be unlawful for any person to use "
        "any unfair method of competition or any unfair or deceptive act or "
        "practice in the conduct of any trade or commerce within this state.\n",
        "nh-358-a",
    )
    assert [u.section_key for u in units] == ["us-nh/rsa/358-A:1", "us-nh/rsa/358-A:2"]

    ors = make_spec(id="us-or-udap", jurisdiction="US-OR")
    units = _split(
        ors,
        "646.605 Definitions for ORS 646.605 to 646.652. As used in ORS 646.605 "
        "to 646.652, unless the context requires otherwise, the following terms "
        "have the meanings given to them under Oregon trade practices law.\n"
        "646.608 Additional unlawful business, trade practices. (1) A person "
        "engages in an unlawful practice if in the course of business the person "
        "passes off real estate, goods or services as those of another person.\n",
        "or-646",
    )
    assert [u.section_key for u in units] == ["us-or/ors/646.605", "us-or/ors/646.608"]


def test_pa_and_wy_and_nycrr_markers(make_spec):
    pa = make_spec(id="us-pa-udap", jurisdiction="US-PA")
    units = _split(
        pa,
        "Section 2. Definitions. As used in this act certain terms shall have "
        "the meanings ascribed to them in this section of the Pennsylvania law: "
        "(4) “Person” means natural persons, corporations and trusts.\n"
        "Section 3. Unlawful acts or practices. Unfair methods of competition "
        "and unfair or deceptive acts or practices in the conduct of any trade "
        "or commerce are hereby declared unlawful throughout this Commonwealth.\n",
        "pa-utpcpl",
    )
    assert [u.section_key for u in units] == ["us-pa/73ps/201-2", "us-pa/73ps/201-3"]
    assert units[1].citation == "73 P.S. § 201-3"

    wy = make_spec(id="us-wy-udap", jurisdiction="US-WY")
    units = _split(
        wy,
        "40-12-105.  Unlawful deceptive trade practices. (a) A person engages in "
        "a deceptive trade practice unlawful under this act when, in the course "
        "of the person's business, the person advertises merchandise with intent "
        "not to sell it as advertised within the state of Wyoming.\n"
        "40-12-108.  Private remedies. (a) A person relying upon an uncured "
        "unlawful deceptive trade practice may bring an action under this act "
        "for the damages the person has actually suffered as a consumer.\n"
        # full-title PDF continues into chapter 13 — must NOT leak into -108
        "40-13-101.  Short title; blue sky filings. This act is entirely about "
        "something else and may not appear in the last chapter-12 section body "
        "no matter how long this trailing chapter text happens to run on for.\n",
        "wy-40-12",
    )
    assert [u.section_key for u in units] == ["us-wy/stat/40-12-105", "us-wy/stat/40-12-108"]
    assert "blue sky" not in units[-1].text  # stop marker truncated ch. 13+

    dfs = make_spec(id="us-ny-dfs-crypto-ads", jurisdiction="US-NY")
    units = _split(
        dfs,
        "§ 200.18 Advertising and marketing. (a) Each licensee shall "
        "maintain, for examination by the superintendent, copies of all "
        "advertising and marketing materials related to its virtual currency "
        "business activity in New York state under these regulations.\n"
        "§ 200.19 Consumer protection. (a) Disclosure of material risks. "
        "As part of establishing a relationship with a customer each licensee "
        "shall disclose all material risks associated with its products and "
        "services in clear, conspicuous and legible writing in the English language.\n",
        "ny-23nycrr-200",
    )
    assert [u.section_key for u in units] == ["us-ny/23nycrr/200.18", "us-ny/23nycrr/200.19"]
    assert units[0].citation == "23 NYCRR § 200.18"


def test_split_meta_drives_normalizer(make_spec):
    """A chapter FetchResult with split meta is chapter-split, not one unit."""
    from datetime import datetime, timezone

    spec = make_spec(id="us-ct-udap", jurisdiction="US-CT")
    html = (
        "<html><body><main>"
        "<p>Sec. 42-110a. Definitions. As used in this chapter: (1) "
        "“Commissioner” means the Commissioner of Consumer Protection "
        "acting directly or through authorized agents per Connecticut law.</p>"
        "<p>Sec. 42-110b. Unfair trade practices prohibited. (a) No person shall "
        "engage in unfair methods of competition and unfair or deceptive acts or "
        "practices in the conduct of any trade or commerce in this state.</p>"
        "</main></body></html>"
    )
    fetched = FetchResult(
        source_id=spec.id,
        requested_url="https://example.test/chap_735a.htm",
        resolved_url="https://example.test/chap_735a.htm",
        content=html.encode(),
        content_type="text/html",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        meta={"kind": "state_html", "split": "ct-42-110",
              "section_hint": "42-110", "citation_hint": "Conn. Gen. Stat. ch. 735a"},
    )
    units = StateHtmlNormalizer().normalize(fetched, spec)
    assert len(units) == 2
    assert units[0].section_key == "us-ct/gs/42-110a"


def test_unknown_split_key_raises(make_spec):
    from datetime import datetime, timezone

    from adcoherent_rag.normalize.base import NormalizeError

    spec = make_spec(id="us-zz-udap", jurisdiction="US-ZZ")
    fetched = FetchResult(
        source_id=spec.id,
        requested_url="https://example.test/x",
        resolved_url="https://example.test/x",
        content=b"<html><body><p>Sec. 1. Words and more words follow here.</p></body></html>",
        content_type="text/html",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        meta={"kind": "state_html", "split": "not-a-real-config"},
    )
    with pytest.raises(NormalizeError):
        StateHtmlNormalizer().normalize(fetched, spec)
