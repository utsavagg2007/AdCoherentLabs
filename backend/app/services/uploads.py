"""The upload security pipeline — the most dangerous trust boundary (§13.3).

Order, exactly as specified: sniff real MIME (magic bytes) → extension AND
sniffed-MIME allowlist → per-tier size cap → clamd stream scan → raster
images re-encoded with Pillow (strips EXIF, embedded payloads, polyglot
tricks) → sha256 checksum → random storage key under
assets/<org>/<submission>/ → assets row (scan_status='clean').

Files are hostile until every step passes. Nothing is enqueued — and nothing
is charged — for a file that fails here (§10.3: never charged).

v1 accepts only what the engine can analyse: png/jpeg/webp/gif (image),
txt (text), html. pdf/mp4 stay on the storage bucket allowlist for later
phases but are rejected here with 415 (decision note: credit_costs defines
no price for them and Layers 1–2 take image|text|html only).
"""

from __future__ import annotations

import hashlib
import io
import secrets
from dataclasses import dataclass

import structlog
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..errors import ApiError

logger = structlog.get_logger("app.uploads")

# sniffed MIME → (engine kind, storage extension)
_MIME_ALLOWLIST: dict[str, tuple[str, str]] = {
    "image/png":  ("image", "png"),
    "image/jpeg": ("image", "jpg"),
    "image/webp": ("image", "png"),   # re-encoded to png
    "image/gif":  ("image", "png"),   # first frame, re-encoded to png
    "text/plain": ("text", "txt"),
    "text/html":  ("html", "html"),
}
_EXT_KIND: dict[str, str] = {
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
    "gif": "image", "txt": "text", "html": "html", "htm": "html",
}
_TEXT_HTML_CAP = 2 * 1024 * 1024   # inline creatives are small; 2 MB is generous


@dataclass
class ProcessedUpload:
    kind: str                # text | image | html
    data: bytes              # bytes as they will be stored (post re-encode)
    content_type: str
    extension: str
    checksum: str            # sha256 of the stored bytes
    original_name: str


def _sniff_mime(data: bytes) -> str:
    import magic

    return magic.from_buffer(data[:16384], mime=True) or "application/octet-stream"


def _clamd_scan(data: bytes) -> None:
    """Stream through clamd; 422 infected (audited by the route), fail-closed
    when the daemon is unreachable and CLAMAV_REQUIRED (prod default)."""
    import clamd

    try:
        daemon = clamd.ClamdNetworkSocket(
            host=settings.clamav_host, port=settings.clamav_port, timeout=60)
        result = daemon.instream(io.BytesIO(data)) or {}
    except Exception as exc:
        if settings.clamav_required:
            logger.error("clamav.unreachable", error=str(exc))
            raise ApiError(503, "scanner_unavailable",
                           "Upload scanning is temporarily unavailable.")
        logger.warning("clamav.skipped - CLAMAV_REQUIRED=false (dev only)")
        return
    status, signature = (result.get("stream") or ("OK", None))[:2]
    if status != "OK":
        raise ApiError(422, "infected_file",
                       "The uploaded file failed the malware scan.",
                       {"signature": str(signature)})


def _reencode_image(data: bytes, sniffed: str) -> tuple[bytes, str, str]:
    """Decode + fully re-encode raster images: EXIF, ICC payloads, appended
    polyglot bytes, and format tricks do not survive a pixel round-trip.
    JPEG stays JPEG (photo weight); everything else lands as PNG."""
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 64_000_000   # decompression-bomb guard
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()                 # structural check pass 1
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if sniffed == "image/jpeg":
                out_format, ext, ctype = "JPEG", "jpg", "image/jpeg"
                img = img.convert("RGB")
            else:
                out_format, ext, ctype = "PNG", "png", "image/png"
                img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            buf = io.BytesIO()
            img.save(buf, format=out_format, quality=92)
            return buf.getvalue(), ext, ctype
    except UnidentifiedImageError:
        raise ApiError(415, "unsupported_media_type",
                       "The file does not decode as an image.")
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, "bad_asset", "The image could not be processed.",
                       {"reason": type(exc).__name__})


async def process_file(data: bytes, filename: str, max_upload_mb: int) -> ProcessedUpload:
    """Run the full pipeline for one uploaded file. Raises ApiError
    (413/415/422/503) on any failed step."""
    cap = max_upload_mb * 1024 * 1024
    if len(data) > cap:
        raise ApiError(413, "payload_too_large",
                       f"Uploads on this plan are capped at {max_upload_mb} MB.",
                       {"max_upload_mb": max_upload_mb})
    if not data:
        raise ApiError(422, "bad_asset", "The uploaded file is empty.")

    sniffed = await run_in_threadpool(_sniff_mime, data)
    if sniffed not in _MIME_ALLOWLIST:
        raise ApiError(415, "unsupported_media_type",
                       "File type is not supported for analysis.",
                       {"sniffed": sniffed,
                        "supported": sorted(_MIME_ALLOWLIST)})
    kind, ext = _MIME_ALLOWLIST[sniffed]

    claimed_ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if claimed_ext and _EXT_KIND.get(claimed_ext) != kind:
        # extension AND content must agree — a renamed .exe dies here even
        # if its bytes happened to sniff as something allowed.
        raise ApiError(415, "unsupported_media_type",
                       "File extension does not match its content.",
                       {"extension": claimed_ext, "sniffed": sniffed})

    if kind in ("text", "html") and len(data) > _TEXT_HTML_CAP:
        raise ApiError(413, "payload_too_large", "Text/HTML creatives are capped at 2 MB.")
    if kind in ("text", "html"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, "bad_asset", "Text/HTML must be valid UTF-8.")

    await run_in_threadpool(_clamd_scan, data)

    content_type = sniffed
    if kind == "image":
        data, ext, content_type = await run_in_threadpool(
            _reencode_image, data, sniffed)

    return ProcessedUpload(
        kind=kind, data=data, content_type=content_type, extension=ext,
        checksum=hashlib.sha256(data).hexdigest(),
        original_name=filename or f"upload.{ext}")


async def process_inline(kind: str, content: str) -> ProcessedUpload:
    """JSON text/html submissions ride the same pipeline minus the image leg
    (still scanned — pasted HTML is as hostile as an uploaded file)."""
    if kind not in ("text", "html"):
        raise ApiError(415, "unsupported_media_type", "kind must be text or html.")
    data = (content or "").encode("utf-8")
    if not data.strip():
        raise ApiError(422, "bad_asset", "Content is empty.")
    if len(data) > _TEXT_HTML_CAP:
        raise ApiError(413, "payload_too_large", "Text/HTML creatives are capped at 2 MB.")
    await run_in_threadpool(_clamd_scan, data)
    ext = "txt" if kind == "text" else "html"
    return ProcessedUpload(
        kind=kind, data=data,
        content_type="text/plain" if kind == "text" else "text/html",
        extension=ext, checksum=hashlib.sha256(data).hexdigest(),
        original_name=f"inline.{ext}")


def storage_key(org_id: str, submission_id: str, extension: str) -> str:
    """Random key under the org/submission prefix (0005 policy convention)."""
    return f"{org_id}/{submission_id}/{secrets.token_hex(16)}.{extension}"
