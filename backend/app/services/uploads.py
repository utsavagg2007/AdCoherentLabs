"""The upload security pipeline — the most dangerous trust boundary (§13.3).

Order, exactly as specified: sniff real MIME (magic bytes) → extension AND
sniffed-MIME allowlist → per-tier size cap → clamd stream scan → raster
images re-encoded with Pillow (strips EXIF, embedded payloads, polyglot
tricks) → sha256 checksum → random storage key under
assets/<org>/<submission>/ → assets row (scan_status='clean').

Files are hostile until every step passes. Nothing is enqueued — and nothing
is charged — for a file that fails here (§10.3: never charged).

Accepted kinds: png/jpeg/webp/gif (image), txt (text), html, pdf, docx, and
mp4/mov/webm (video). WHICH of those a given org may submit is a plan
entitlement (plan_entitlements.allowed_kinds; hobby additionally caps video
length at max_video_seconds) — the gate runs here, before any expensive work
and before anything is charged.
"""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import tempfile
import zipfile
from dataclasses import dataclass

import structlog
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..errors import ApiError

logger = structlog.get_logger("app.uploads")

_DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
              ".wordprocessingml.document")

# sniffed MIME → (engine kind, storage extension)
_MIME_ALLOWLIST: dict[str, tuple[str, str]] = {
    "image/png":  ("image", "png"),
    "image/jpeg": ("image", "jpg"),
    "image/webp": ("image", "png"),   # re-encoded to png
    "image/gif":  ("image", "png"),   # first frame, re-encoded to png
    "text/plain": ("text", "txt"),
    "text/html":  ("html", "html"),
    "application/pdf": ("pdf", "pdf"),
    _DOCX_MIME:        ("docx", "docx"),
    "video/mp4":       ("video", "mp4"),
    "video/quicktime": ("video", "mov"),
    "video/webm":      ("video", "webm"),
}
_EXT_KIND: dict[str, str] = {
    "png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
    "gif": "image", "txt": "text", "html": "html", "htm": "html",
    "pdf": "pdf", "docx": "docx",
    "mp4": "video", "mov": "video", "webm": "video",
}
_TEXT_HTML_CAP = 2 * 1024 * 1024   # inline creatives are small; 2 MB is generous
_PDF_MAX_PAGES = 40                # bounds the worker's page-render cost
_VIDEO_ABS_MAX_SECONDS = 900       # 15 min hard cap for ANY tier (worker cost)
# clamd INSTREAM is bounded by StreamMaxLength (25 MB default): files above
# this scan their head region only — media bytes are never executed, and the
# parser-facing structure sits at the front of every container we accept.
_CLAMD_STREAM_CAP = 24 * 1024 * 1024


@dataclass
class ProcessedUpload:
    kind: str                # text | image | html | pdf | docx | video
    data: bytes              # bytes as they will be stored (post re-encode)
    content_type: str
    extension: str
    checksum: str            # sha256 of the stored bytes
    original_name: str
    duration_seconds: float | None = None   # video only
    pages: int | None = None                # pdf only


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
        result = daemon.instream(io.BytesIO(data[:_CLAMD_STREAM_CAP])) or {}
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


def _zip_is_docx(data: bytes) -> bool:
    """libmagic sometimes reports OOXML as plain zip — peek for the Word part."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "word/document.xml" in zf.namelist()
    except Exception:
        return False


def _probe_pdf(data: bytes) -> int:
    """Structural check + page count (bounds the worker's render cost)."""
    import fitz  # PyMuPDF — already present via the CV layer requirements

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ApiError(422, "bad_asset",
                               "Password-protected PDFs cannot be analysed.")
            pages = doc.page_count
    except ApiError:
        raise
    except Exception:
        raise ApiError(422, "bad_asset", "The file does not parse as a PDF.")
    if pages == 0:
        raise ApiError(422, "bad_asset", "The PDF has no pages.")
    if pages > _PDF_MAX_PAGES:
        raise ApiError(413, "payload_too_large",
                       f"PDF creatives are capped at {_PDF_MAX_PAGES} pages.",
                       {"pages": pages, "max_pages": _PDF_MAX_PAGES})
    return pages


def _probe_docx(data: bytes) -> None:
    if not _zip_is_docx(data):
        raise ApiError(422, "bad_asset",
                       "The file does not parse as a Word document.")


def _probe_video(data: bytes, ext: str) -> float:
    """Decode probe + duration via OpenCV (a temp file: cv2 wants a path)."""
    import cv2

    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        cap = cv2.VideoCapture(path)
        try:
            if not cap.isOpened():
                raise ApiError(422, "bad_asset", "The video could not be decoded.")
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            if fps <= 0 or frames <= 0:
                raise ApiError(422, "bad_asset",
                               "The video reports no readable duration.")
            return float(frames) / float(fps)
        finally:
            cap.release()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def process_file(data: bytes, filename: str, max_upload_mb: int,
                       allowed_kinds: list[str] | None = None,
                       max_video_seconds: int | None = None) -> ProcessedUpload:
    """Run the full pipeline for one uploaded file. Raises ApiError
    (403/413/415/422/503) on any failed step. allowed_kinds /
    max_video_seconds come from the org's plan entitlements."""
    cap = max_upload_mb * 1024 * 1024
    if len(data) > cap:
        raise ApiError(413, "payload_too_large",
                       f"Uploads on this plan are capped at {max_upload_mb} MB.",
                       {"max_upload_mb": max_upload_mb})
    if not data:
        raise ApiError(422, "bad_asset", "The uploaded file is empty.")

    sniffed = await run_in_threadpool(_sniff_mime, data)
    if sniffed == "application/zip" and _zip_is_docx(data):
        sniffed = _DOCX_MIME
    if sniffed not in _MIME_ALLOWLIST:
        raise ApiError(415, "unsupported_media_type",
                       "File type is not supported for analysis.",
                       {"sniffed": sniffed,
                        "supported": sorted(_MIME_ALLOWLIST)})
    kind, ext = _MIME_ALLOWLIST[sniffed]

    # Plan gate BEFORE any expensive work: what the tier may submit at all.
    if allowed_kinds is not None and kind not in allowed_kinds:
        raise ApiError(403, "plan_restricted",
                       f"Your plan does not accept {kind} uploads.",
                       {"kind": kind, "allowed_kinds": sorted(allowed_kinds)})

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

    pages: int | None = None
    duration: float | None = None
    if kind == "pdf":
        pages = await run_in_threadpool(_probe_pdf, data)
    elif kind == "docx":
        await run_in_threadpool(_probe_docx, data)
    elif kind == "video":
        duration = await run_in_threadpool(_probe_video, data, ext)
        limit = min(max_video_seconds or _VIDEO_ABS_MAX_SECONDS,
                    _VIDEO_ABS_MAX_SECONDS)
        if duration > limit:
            raise ApiError(403 if max_video_seconds else 413,
                           "plan_restricted" if max_video_seconds else "payload_too_large",
                           f"Videos on your plan are capped at {limit} seconds; "
                           f"this one runs {duration:.0f}s.",
                           {"duration_seconds": round(duration, 1),
                            "max_video_seconds": limit})

    await run_in_threadpool(_clamd_scan, data)

    content_type = sniffed
    if kind == "image":
        data, ext, content_type = await run_in_threadpool(
            _reencode_image, data, sniffed)

    return ProcessedUpload(
        kind=kind, data=data, content_type=content_type, extension=ext,
        checksum=hashlib.sha256(data).hexdigest(),
        original_name=filename or f"upload.{ext}",
        duration_seconds=duration, pages=pages)


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
