"""Profile-image decoding, validation and normalisation.

Kept separate from `clients.aws.storage` so it can be unit-tested without AWS
credentials, and reused by any flow that needs a safe, web-optimised raster.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


# HEIC/HEIF is what iOS cameras produce by default. Pillow cannot decode it
# alone, so register the pillow-heif plugin here — this module is imported by
# both the serializer and the worker task, so one registration covers the
# validation path and the processing path.
#
# Guarded so a deployment without the wheel degrades to "HEIC rejected with a
# clear message" instead of failing deep inside the worker.
try:
    import pillow_heif
except ImportError:  # pragma: no cover - depends on deployment
    HEIF_SUPPORTED = False
    logger.warning("pillow-heif not installed — HEIC/HEIF uploads will be rejected.")
else:
    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True


# Pillow reports every HEIC/HEIF variant as format "HEIF" once registered.
_BASE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
_BASE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_HEIF_FORMATS = {"HEIF"}
_HEIF_EXTENSIONS = {".heic", ".heif", ".hif"}

# Formats Pillow can actually decode in this build.
ALLOWED_FORMATS: frozenset[str] = frozenset(
    _BASE_FORMATS | (_HEIF_FORMATS if HEIF_SUPPORTED else set())
)

# Extensions advertised to clients / used for serializer-level rejection.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    _BASE_EXTENSIONS | (_HEIF_EXTENSIONS if HEIF_SUPPORTED else set())
)

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB

# Decompression-bomb ceiling. A 50 MP source is far beyond any profile picture
# and keeps worst-case decode memory bounded (~200 MB at RGBA).
MAX_SOURCE_PIXELS = 50_000_000

# Longest-edge target per profile image slot. Downscaling here is the single
# biggest win for storage cost, CDN egress and client render time.
MAX_EDGE_BY_FIELD: dict[str, int] = {
    "avatar": 512,
    "display_photo": 512,
    "cover_photo": 1600,
}
DEFAULT_MAX_EDGE = 1024

JPEG_QUALITY = 85


class ImageValidationError(ValueError):
    """Raised when a candidate upload is not a usable image."""


def probe(raw: bytes) -> dict[str, Any]:
    """Cheap header-only inspection. Does not decode pixel data.

    Raises ImageValidationError if the bytes are not a supported image.
    """
    try:
        with Image.open(BytesIO(raw)) as img:
            fmt = (img.format or "").upper()
            width, height = img.size
    except Exception as exc:
        raise ImageValidationError("File is not a readable image.") from exc

    if fmt not in ALLOWED_FORMATS:
        raise ImageValidationError(
            f"Unsupported image format: {fmt or 'unknown'}. "
            f"Allowed: {', '.join(sorted(ALLOWED_FORMATS))}."
        )

    if width * height > MAX_SOURCE_PIXELS:
        raise ImageValidationError("Image resolution is too large.")

    return {"format": fmt, "width": width, "height": height}


def normalize(raw: bytes, *, max_edge: int) -> dict[str, Any]:
    """Decode, orient, downscale and re-encode a profile image.

    Returns the encoded buffer plus the metadata the Media row needs. Output is
    always progressive JPEG: universally decodable, small, and it drops every
    source metadata block (including EXIF GPS coordinates) as a side effect.
    """
    try:
        with Image.open(BytesIO(raw)) as img:
            source_format = (img.format or "").upper()
            if source_format not in ALLOWED_FORMATS:
                raise ImageValidationError(
                    f"Unsupported image format: {source_format or 'unknown'}."
                )

            # Honour the EXIF orientation tag, then discard EXIF entirely.
            img = ImageOps.exif_transpose(img)

            # Flatten transparency onto white; JPEG has no alpha channel.
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                canvas = Image.new("RGB", img.size, (255, 255, 255))
                canvas.paste(img, mask=img.split()[-1])
                img = canvas
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Only ever downscale — upscaling a small avatar wastes bytes.
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)

            buffer = BytesIO()
            img.save(
                buffer,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
            width, height = img.size
    except ImageValidationError:
        raise
    except Exception as exc:
        raise ImageValidationError("Image could not be processed.") from exc

    size = buffer.tell()
    buffer.seek(0)
    return {
        "buffer": buffer,
        "width": width,
        "height": height,
        "content_type": "image/jpeg",
        "extension": ".jpg",
        "file_size_bytes": size,
        "source_format": source_format,
    }


def max_edge_for(field: str) -> int:
    return MAX_EDGE_BY_FIELD.get(field, DEFAULT_MAX_EDGE)
