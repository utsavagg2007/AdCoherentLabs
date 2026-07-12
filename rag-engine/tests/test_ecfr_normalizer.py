"""EcfrXmlNormalizer against the synthetic Regulation-DD-like fixture."""

import pytest

from adcoherent_rag.normalize.base import NormalizeError
from adcoherent_rag.normalize.ecfr_xml import EcfrXmlNormalizer

from conftest import FIXTURES


@pytest.fixture
def units(make_spec, make_fetch_result):
    spec = make_spec(id="cfpb-reg-dd-tisa", citation="12 CFR Part 1030 (advertising: § 1030.8)")
    fetched = make_fetch_result(
        FIXTURES.joinpath("ecfr_sample.xml").read_bytes(),
        source_id=spec.id,
        content_type="application/xml",
        meta={"kind": "ecfr_xml", "cfr_title": 12, "cfr_part": 1030,
              "ecfr_date": "2026-07-01", "section_amend_dates": {}},
    )
    return EcfrXmlNormalizer().normalize(fetched, spec)


def test_sections_and_appendix_extracted(units):
    keys = [u.section_key for u in units]
    assert "cfr/12/1030.1" in keys
    assert "cfr/12/1030.8" in keys
    assert any(k.startswith("cfr/12/1030/appendix-") for k in keys)


def test_citation_and_heading(units):
    adv = next(u for u in units if u.section_key == "cfr/12/1030.8")
    assert adv.citation == "12 CFR § 1030.8"
    assert adv.heading == "Advertising."


def test_paragraph_labels_and_nesting(units):
    adv = next(u for u in units if u.section_key == "cfr/12/1030.8")
    labels = [p.label for p in adv.paragraphs]
    assert "(a)" in labels and "(b)" in labels and "(c)" in labels
    nested = next(p for p in adv.paragraphs if p.label == "(a)(1)")
    assert nested.indent_level >= 1
    assert "free" in nested.text


def test_notes_are_skipped(units):
    adv = next(u for u in units if u.section_key == "cfr/12/1030.8")
    assert "This should be skipped" not in adv.text
    first = next(u for u in units if u.section_key == "cfr/12/1030.1")
    assert "79276" not in first.text  # CITA content skipped


def test_invalid_xml_raises(make_spec, make_fetch_result):
    spec = make_spec()
    fetched = make_fetch_result(b"not xml at all", meta={"kind": "ecfr_xml", "cfr_title": 12, "cfr_part": 1030})
    with pytest.raises(NormalizeError):
        EcfrXmlNormalizer().normalize(fetched, spec)
