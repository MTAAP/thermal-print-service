from __future__ import annotations

import copy
import io
from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from printer_core.constants import PRINT_HEAD_WIDTH_PX

# Band geometry. Fixed pixel values keep the raster output deterministic across
# renderer versions (the band is composited here, not by the local renderer).
_BAND_HEIGHT_PX = 44
_BAND_PAD_X = 24  # matches the live-area gutter so the label aligns with body text
_MAX_RAW_HEIGHT_DEFAULT = 16_000  # ServiceConfig.max_raw_height_px default
_MAX_DECODED_IMAGE_PIXELS_DEFAULT = 10_000_000  # ServiceConfig default


def from_label(sender: str, sent_at: str) -> str:
    """FROM <HANDLE> . HH:MM, derived purely from immutable hub fields.

    No local clock read (spec 7.2): a redelivered job must produce the exact
    same label so the local idempotency layer dedups it instead of 409-ing."""
    ts = sent_at[:-1] + "+00:00" if sent_at.endswith("Z") else sent_at
    when = datetime.fromisoformat(ts)
    # The middot separator matches the spec's "FROM ALICE . 14:32" rendering.
    return f"FROM {sender.upper()} · {when.strftime('%H:%M')}"


def from_header_block(doc: dict[str, Any], *, sender: str, sent_at: str) -> dict[str, Any]:
    """Return a NEW document with a bold FROM paragraph prepended.

    Uses a bold ``paragraph`` (common-core, stable across renderer versions),
    not an ``inverse_band`` header: white-on-black at body size is illegible on
    this head (project MEMORY note). Non-mutating + deterministic."""
    out = copy.deepcopy(doc)
    blocks = out.get("blocks")
    if not isinstance(blocks, list):
        # Defensive: a doc with no blocks list is the local validator's problem
        # (downstream 400 -> rejected_incompatible). We still attach the tag so
        # attribution is never silently dropped.
        blocks = []
    tag = {"type": "paragraph", "text": from_label(sender, sent_at), "emphasis": "bold"}
    out["blocks"] = [tag, *blocks]
    return out


def _render_band(label: str) -> Image.Image:
    band = Image.new("L", (PRINT_HEAD_WIDTH_PX, _BAND_HEIGHT_PX), color=255)
    draw = ImageDraw.Draw(band)
    # Default PIL bitmap font: deterministic across machines (no font-file
    # dependency, no anti-aliasing variance) so the band bytes are stable. The
    # local raw pipeline dithers/prints it as-is; this is attribution, not
    # typography, so the renderer-is-truth invariant is not violated.
    font = ImageFont.load_default()
    draw.text((_BAND_PAD_X, 14), label, fill=0, font=font)
    # A hairline rule under the band visually separates it from the image.
    draw.line([(0, _BAND_HEIGHT_PX - 1), (PRINT_HEAD_WIDTH_PX - 1, _BAND_HEIGHT_PX - 1)], fill=0)
    return band


def composite_from_band(
    png_bytes: bytes, *, sender: str, sent_at: str,
    max_raw_height_px: int = _MAX_RAW_HEIGHT_DEFAULT,
    max_decoded_image_pixels: int = _MAX_DECODED_IMAGE_PIXELS_DEFAULT,
) -> bytes:
    """Composite a 576px FROM band ABOVE the incoming PNG (spec 7.4).

    Width must stay exactly PRINT_HEAD_WIDTH_PX and band+image height must stay
    within max_raw_height_px (the local /print/raw 400/413s otherwise)."""
    # A friend's raw payload is untrusted bytes. Decode failures must surface as
    # ValueError -- the deterministic "malformed payload" contract process_job
    # catches to mark the job terminally failed -- NOT as an OSError that escapes
    # into the run_forever backoff loop and redelivers the poison forever.
    # UnidentifiedImageError is an OSError; a decompression bomb is a
    # DecompressionBombError (neither a ValueError nor an OSError); a truncated
    # PNG raises OSError on access. Normalize them all here.
    try:
        with Image.open(io.BytesIO(png_bytes)) as opened:
            width, height = opened.size
            if width != PRINT_HEAD_WIDTH_PX:
                raise ValueError(f"raw image must be exactly {PRINT_HEAD_WIDTH_PX}px wide")
            pixels = width * height
            if pixels > max_decoded_image_pixels:
                raise ValueError(
                    f"raw image has {pixels} pixels; max_decoded_image_pixels="
                    f"{max_decoded_image_pixels}"
                )
            total_h = _BAND_HEIGHT_PX + height
            if total_h > max_raw_height_px:
                raise ValueError(f"band+image height {total_h} exceeds max_raw_height_px")
            src = opened.convert("L")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"raw payload is not a decodable image: {exc}") from exc
    band = _render_band(from_label(sender, sent_at))
    canvas = Image.new("L", (PRINT_HEAD_WIDTH_PX, total_h), color=255)
    canvas.paste(band, (0, 0))
    canvas.paste(src, (0, _BAND_HEIGHT_PX))
    out = io.BytesIO()
    # optimize=True is deterministic for a given Pillow version; pin nothing
    # extra — the relay and the local Pi share the same Pillow (printer-core).
    canvas.save(out, format="PNG")
    return out.getvalue()
