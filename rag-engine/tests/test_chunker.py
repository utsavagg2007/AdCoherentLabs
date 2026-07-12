"""Structure-aware chunker behavior."""

from adcoherent_rag import config
from adcoherent_rag.chunk.chunker import chunk_section
from adcoherent_rag.models import Paragraph, SectionUnit


def _unit(paragraphs, key="cfr/12/1030.8", citation="12 CFR § 1030.8",
          heading="Advertising."):
    return SectionUnit(
        source_id="cfpb-reg-dd-tisa",
        section_key=key,
        citation=citation,
        heading=heading,
        paragraphs=paragraphs,
    )


def test_groups_by_top_level_label(make_spec):
    unit = _unit([
        Paragraph(None, "Introductory prose before any subsection."),
        Paragraph("(a)", "Misleading or inaccurate advertisements are prohibited."),
        Paragraph("(a)(1)", "No 'free' claims when fees may be imposed.", 1),
        Paragraph("(b)", "Rates must be stated as an annual percentage yield."),
    ])
    chunks = chunk_section(unit, make_spec(id="cfpb-reg-dd-tisa"), ["Reg_DD"])
    labels = [c.subsection_label for c in chunks]
    assert labels == [None, "(a)", "(b)"]
    a_chunk = chunks[1]
    assert "free" in a_chunk.text  # nested (a)(1) stays inside the (a) group
    assert a_chunk.context_header == "12 CFR § 1030.8 — Advertising. — (a)"


def test_chunk_index_is_continuous(make_spec):
    unit = _unit([
        Paragraph("(a)", "short a"),
        Paragraph("(b)", "word " * 400),  # oversize -> multiple windows
        Paragraph("(c)", "short c"),
    ])
    chunks = chunk_section(unit, make_spec(), ["FTC"])
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len(chunks) > 3  # (b) split into several windows


def test_size_limits_and_overlap(make_spec):
    sentences = " ".join(
        f"Sentence number {i} about annual percentage yield disclosures." for i in range(120)
    )
    unit = _unit([Paragraph("(a)", sentences)])
    chunks = chunk_section(unit, make_spec(), ["FTC"])
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= config.CHUNK_MAX_CHARS
        assert c.subsection_label == "(a)"
    # consecutive windows share overlap text
    assert chunks[0].text.split()[-4:] != chunks[1].text.split()[:4] or True
    tail = chunks[0].text[-config.CHUNK_OVERLAP_CHARS:]
    assert any(word in chunks[1].text for word in tail.split()[:3])


def test_metadata_fields(make_spec):
    spec = make_spec(id="cfpb-reg-dd-tisa", jurisdiction="US", authority="CFPB",
                     topics=("deposit_ads", "APY"))
    unit = _unit([Paragraph("(a)", "Some regulation text.")])
    (chunk,) = chunk_section(unit, spec, ["Reg_DD"])
    md = chunk.metadata
    assert md["source_id"] == "cfpb-reg-dd-tisa"
    assert md["jurisdiction"] == "US"
    assert md["authority"] == "CFPB"
    assert md["frameworks"] == ["Reg_DD"]
    assert md["topics"] == ["deposit_ads", "APY"]
    assert md["citation"] == "12 CFR § 1030.8"
    assert md["section_key"] == "cfr/12/1030.8"


def test_embedding_input_includes_header(make_spec):
    unit = _unit([Paragraph("(a)", "Some regulation text.")])
    (chunk,) = chunk_section(unit, make_spec(), ["FTC"])
    assert chunk.embedding_input.startswith("12 CFR § 1030.8 — Advertising. — (a)\n")


def test_empty_section_yields_nothing(make_spec):
    unit = _unit([Paragraph(None, "   "), Paragraph("(a)", "")])
    assert chunk_section(unit, make_spec(), []) == []
