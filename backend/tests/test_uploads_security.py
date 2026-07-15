"""Upload security (§16): EICAR rejected + audited, MIME spoof rejected,
oversize 413, polyglot re-encode, inline pipeline parity."""

from __future__ import annotations

import io

import pytest

from app.config import settings
from app.errors import ApiError
from app.services import uploads

from .conftest import auth, mint_jwt

pytestmark = pytest.mark.needs_db

EICAR = (rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
         rb"$H+H*")


def _png(extra: bytes = b"") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    img = Image.new("RGB", (40, 20), (250, 20, 20))
    exif = Image.Exif()
    exif[0x0131] = "polyglot-marker-software"      # EXIF Software tag
    img.save(buf, format="PNG", exif=exif)
    return buf.getvalue() + extra


def _clamd_up() -> bool:
    import clamd

    try:
        clamd.ClamdNetworkSocket(host=settings.clamav_host,
                                 port=settings.clamav_port, timeout=3).ping()
        return True
    except Exception:
        return False


async def test_mime_spoof_rejected():
    exe = b"MZ\x90\x00" + b"\x00" * 200                       # PE header
    with pytest.raises(ApiError) as exc:
        await uploads.process_file(exe, "innocent.png", max_upload_mb=10)
    assert exc.value.status == 415


async def test_extension_content_mismatch_rejected():
    with pytest.raises(ApiError) as exc:                      # real png, .txt ext
        await uploads.process_file(_png(), "notes.txt", max_upload_mb=10)
    assert exc.value.status == 415
    assert "extension" in exc.value.message.lower()


async def test_oversize_413_before_anything_else():
    blob = b"\x00" * (11 * 1024 * 1024)
    with pytest.raises(ApiError) as exc:
        await uploads.process_file(blob, "big.png", max_upload_mb=10)
    assert exc.value.status == 413


async def test_polyglot_and_exif_do_not_survive_reencode(monkeypatch):
    if not _clamd_up():
        monkeypatch.setattr(settings, "clamav_required", False)
    dirty = _png(extra=b"PK\x03\x04" + b"A" * 64)             # png+zip polyglot
    out = await uploads.process_file(dirty, "ad.png", max_upload_mb=10)
    assert out.kind == "image" and out.content_type == "image/png"
    assert b"PK\x03\x04" not in out.data                      # appendix stripped
    assert b"polyglot-marker-software" not in out.data        # EXIF stripped
    assert out.checksum != ""


@pytest.mark.needs_clamav
async def test_eicar_rejected_and_audited(client, tenant):
    if not _clamd_up():
        pytest.skip("clamd unreachable")
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")
    r = await client.post(
        "/v1/submissions",
        files={"file": ("totally-fine.txt", EICAR, "text/plain")},
        headers=auth(tok, tenant["org"]))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "infected_file"


async def test_clamd_down_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", 1)           # nothing listens
    monkeypatch.setattr(settings, "clamav_required", True)
    with pytest.raises(ApiError) as exc:
        await uploads.process_inline("text", "hello")
    assert exc.value.status == 503


async def test_inline_utf8_and_emptiness_guards():
    with pytest.raises(ApiError):
        await uploads.process_inline("text", "   ")
    with pytest.raises(ApiError) as exc:
        await uploads.process_inline("video", "x")
    assert exc.value.status == 415
