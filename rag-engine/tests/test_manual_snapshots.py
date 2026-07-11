"""Manual snapshot ingestion: local files for manual_stub sources."""

from pathlib import Path

import pytest

from adcoherent_rag import config
from adcoherent_rag.fetch.base import FetchError
from adcoherent_rag.fetch.manual import ManualFetcher, manual_files_for
from adcoherent_rag.normalize.manual import ManualSnapshotNormalizer

_HTML = b"""
<html><body><main>
<h1>N.J. Rev. Stat. 56:8-2</h1>
<p>(a) The act, use or employment by any person of any deception, fraud,
false pretense, false promise, or misrepresentation in connection with the
sale or advertisement of any merchandise is an unlawful practice.</p>
<p>(b) Advertisement includes the attempt by publication to induce any
person to enter into any obligation or acquire any title or interest in
merchandise.</p>
</main></body></html>
"""


@pytest.fixture
def manual_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MANUAL_SNAPSHOT_DIR", tmp_path)
    return tmp_path


def _stub_spec(make_spec):
    return make_spec(id="us-nj-udap", category="state_udap", jurisdiction="US-NJ")


def test_no_files_means_empty_list(manual_dir, make_spec):
    assert manual_files_for(_stub_spec(make_spec)) == []


def test_fetcher_raises_without_files(manual_dir, make_spec):
    with pytest.raises(FetchError):
        ManualFetcher().fetch(_stub_spec(make_spec))


def test_html_snapshot_roundtrip(manual_dir, make_spec):
    spec = _stub_spec(make_spec)
    src = manual_dir / spec.id
    src.mkdir()
    (src / "njsa-56-8-2.html").write_bytes(_HTML)
    (src / "notes.docx").write_bytes(b"ignored")  # unsupported ext filtered out

    results = ManualFetcher().fetch(spec)
    assert len(results) == 1
    fetched = results[0]
    assert fetched.meta["kind"] == "manual_html"
    assert fetched.meta["manual_file"] == "njsa-56-8-2.html"
    assert fetched.requested_url.startswith("file://")

    units = ManualSnapshotNormalizer().normalize(fetched, spec)
    assert len(units) == 1
    unit = units[0]
    # section keys are namespaced by file stem so files never collide
    assert unit.section_key == "us-nj-udap/njsa-56-8-2"
    assert "unlawful practice" in unit.text
    labels = [p.label for p in unit.paragraphs]
    assert "(a)" in labels and "(b)" in labels


def test_two_files_get_distinct_keys(manual_dir, make_spec):
    spec = _stub_spec(make_spec)
    src = manual_dir / spec.id
    src.mkdir()
    (src / "sec-1.html").write_bytes(_HTML)
    (src / "sec-2.html").write_bytes(_HTML + b"<!-- differs -->")

    norm = ManualSnapshotNormalizer()
    keys = {
        u.section_key
        for fetched in ManualFetcher().fetch(spec)
        for u in norm.normalize(fetched, spec)
    }
    assert keys == {"us-nj-udap/sec-1", "us-nj-udap/sec-2"}


def test_empty_file_is_skipped(manual_dir, make_spec):
    spec = _stub_spec(make_spec)
    src = manual_dir / spec.id
    src.mkdir()
    (src / "empty.html").write_bytes(b"   ")
    (src / "real.html").write_bytes(_HTML)

    results = ManualFetcher().fetch(spec)
    assert [r.meta["manual_file"] for r in results] == ["real.html"]


def test_pipeline_dry_run_uses_manual_files(manual_dir, make_spec):
    """End-to-end (offline): manual_stub source ingests via local files."""
    from adcoherent_rag.pipeline import _ingest_one
    from adcoherent_rag.manifest import get_source

    spec = get_source("us-nj-udap")
    src = manual_dir / spec.id
    src.mkdir()
    (src / "njsa-56-8-2.html").write_bytes(_HTML)

    outcome = _ingest_one(
        spec, conn=None, run_id=None, embedder=None, force=False, dry_run=True
    )
    assert outcome["status"] == "stored"
    assert outcome["sections"] == 1
    assert outcome["chunks"] >= 1


def test_pipeline_dry_run_skips_without_files(manual_dir, make_spec):
    from adcoherent_rag.pipeline import _ingest_one
    from adcoherent_rag.manifest import get_source

    spec = get_source("us-nj-udap")
    outcome = _ingest_one(
        spec, conn=None, run_id=None, embedder=None, force=False, dry_run=True
    )
    assert outcome["status"] == "skipped"
    assert "save the official text" in outcome["reason"]
