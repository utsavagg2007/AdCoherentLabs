"""HTML helpers + uscode/state normalizers on synthetic fixtures."""

import pytest

from adcoherent_rag.models import Paragraph
from adcoherent_rag.normalize.html_generic import (
    GenericHtmlNormalizer,
    UscodeHtmlNormalizer,
    extract_leading_label,
    extract_main_text,
    split_labeled_paragraphs,
)
from adcoherent_rag.normalize.statute_html import StateHtmlNormalizer


# ---------------------------------------------------------------------------
# shared helpers


def test_extract_main_text_drops_chrome():
    html = """
    <html><head><script>evil()</script><style>.x{}</style></head>
    <body>
      <nav>Home | About | Sitemap</nav>
      <main><p>The statute text lives here.</p><p>(a) First subsection.</p></main>
      <footer>© 2026 Some State</footer>
    </body></html>
    """
    text = extract_main_text(html)
    assert "statute text lives here" in text
    assert "Sitemap" not in text
    assert "© 2026" not in text
    assert "evil()" not in text


def test_extract_leading_label():
    assert extract_leading_label("(a) Foo bar")[0] == "(a)"
    label, rest, indent = extract_leading_label("(a)(1) Nested text")
    assert label == "(a)(1)" and rest == "Nested text" and indent >= 1
    assert extract_leading_label("(ii) Romanette")[2] == 2
    assert extract_leading_label("No label here")[0] is None


def test_split_labeled_paragraphs():
    text = "Intro prose line.\n(a) First subsection text.\n(b) Second one.\ncontinuation of b.\n\nNew unlabeled paragraph."
    paragraphs = split_labeled_paragraphs(text)
    labels = [p.label for p in paragraphs]
    assert labels == [None, "(a)", "(b)", None]
    b = paragraphs[2]
    assert "continuation of b" in b.text


# ---------------------------------------------------------------------------
# uscode


_USCODE_HTML = b"""
<html><body>
  <div class="section-head">&#167;45. Unfair methods of competition unlawful; prevention by Commission</div>
  <div class="statutory-body">(a) Declaration of unlawfulness; power to prohibit unfair practices</div>
  <div class="statutory-body-1em">(1) Unfair methods of competition in or affecting commerce are hereby declared unlawful.</div>
  <div class="statutory-body">(b) Proceeding by Commission; modifying and setting aside orders</div>
</body></html>
"""


def test_uscode_normalizer(make_spec, make_fetch_result):
    spec = make_spec(id="ftc-act-section-5", category="federal_statute",
                     citation="15 U.S.C. § 45")
    fetched = make_fetch_result(
        _USCODE_HTML, source_id=spec.id,
        meta={"kind": "uscode_html", "usc_title": 15, "usc_section": "45"},
    )
    (unit,) = UscodeHtmlNormalizer().normalize(fetched, spec)
    assert unit.section_key == "usc/15/45"
    assert unit.citation == "15 U.S.C. § 45"
    assert unit.heading and unit.heading.startswith("Unfair methods")
    labels = [p.label for p in unit.paragraphs]
    assert "(a)" in labels and "(b)" in labels
    nested = next(p for p in unit.paragraphs if p.label == "(1)")
    assert nested.indent_level >= 1


# ---------------------------------------------------------------------------
# state pages


def test_state_single_section(make_spec, make_fetch_result):
    spec = make_spec(id="us-ca-udap", category="state_udap", jurisdiction="US-CA",
                     citation="Cal. Bus. & Prof. Code §§ 17200, 17500")
    html = b"""<html><body><main>
      <h3>17500.</h3>
      <p>It is unlawful for any person to make or disseminate any statement
      which is untrue or misleading, and which is known to be untrue or misleading.</p>
    </main></body></html>"""
    fetched = make_fetch_result(
        html, source_id=spec.id,
        meta={"kind": "state_html", "section_hint": "17500",
              "citation_hint": "Cal. Bus. & Prof. Code § 17500"},
    )
    (unit,) = StateHtmlNormalizer().normalize(fetched, spec)
    assert unit.section_key == "us-ca/17500"
    assert unit.citation == "Cal. Bus. & Prof. Code § 17500"
    assert "untrue or misleading" in unit.text


_TX_HTML = b"""<html><body><main>
Sec. 17.41.  SHORT TITLE.  This subchapter may be cited as the Deceptive Trade
Practices-Consumer Protection Act.
Sec. 17.46.  DECEPTIVE TRADE PRACTICES UNLAWFUL.  (a) False, misleading, or
deceptive acts or practices in the conduct of any trade or commerce are hereby
declared unlawful. (b) The term "false, misleading, or deceptive acts or
practices" includes passing off goods or services as those of another.
</main></body></html>"""


def test_state_texas_chapter_split(make_spec, make_fetch_result):
    spec = make_spec(id="us-tx-udap", category="state_udap", jurisdiction="US-TX",
                     citation="Tex. Bus. & Com. Code ch. 17, subch. E")
    fetched = make_fetch_result(
        _TX_HTML, source_id=spec.id,
        meta={"kind": "state_html", "section_hint": "17",
              "citation_hint": "Tex. Bus. & Com. Code ch. 17"},
    )
    units = StateHtmlNormalizer().normalize(fetched, spec)
    keys = [u.section_key for u in units]
    assert "us-tx/bc/17.41" in keys and "us-tx/bc/17.46" in keys
    sec_46 = next(u for u in units if u.section_key == "us-tx/bc/17.46")
    assert sec_46.citation == "Tex. Bus. & Com. Code § 17.46"
    assert any(p.label == "(a)" for p in sec_46.paragraphs)


def test_state_missing_hint_raises(make_spec, make_fetch_result):
    from adcoherent_rag.normalize.base import NormalizeError

    spec = make_spec(id="us-ny-udap", category="state_udap", jurisdiction="US-NY")
    fetched = make_fetch_result(b"<html><body><main>text body here</main></body></html>",
                                source_id=spec.id, meta={"kind": "state_html"})
    with pytest.raises(NormalizeError):
        StateHtmlNormalizer().normalize(fetched, spec)


# ---------------------------------------------------------------------------
# generic


def test_generic_normalizer(make_spec, make_fetch_result):
    spec = make_spec(id="some-ref", citation=None, name="Some Reference")
    html = b"<html><body><h1>Reference Doc</h1><main><p>Body text of the reference.</p></main></body></html>"
    (unit,) = GenericHtmlNormalizer().normalize(make_fetch_result(html, source_id=spec.id), spec)
    assert unit.section_key == "some-ref"
    assert unit.citation == "Some Reference"
    assert "Body text" in unit.text
