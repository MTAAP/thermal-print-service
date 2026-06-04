import io

from PIL import Image
from printer_core.constants import PRINT_HEAD_WIDTH_PX

from printer.relay.from_tag import composite_from_band, from_header_block, from_label


def test_from_label_is_pure_function_of_inputs():
    # No clock read: same inputs -> same label, every time.
    a = from_label("alice", "2026-06-03T14:32:07+00:00")
    b = from_label("alice", "2026-06-03T14:32:07+00:00")
    assert a == b == "FROM ALICE · 14:32"


def test_from_label_handles_z_suffix_utc():
    assert from_label("bob", "2026-06-03T09:05:00Z") == "FROM BOB · 09:05"


def test_from_header_block_prepends_a_stable_block():
    doc = {"blocks": [{"type": "paragraph", "text": "hello"}]}
    out1 = from_header_block(doc, sender="alice", sent_at="2026-06-03T14:32:07+00:00")
    out2 = from_header_block(doc, sender="alice", sent_at="2026-06-03T14:32:07+00:00")
    # Deterministic and non-mutating.
    assert out1 == out2
    assert doc["blocks"][0]["text"] == "hello"  # original untouched
    first = out1["blocks"][0]
    # A bold paragraph, NOT an inverse_band header: white-on-black at body size
    # is illegible on this head (project MEMORY note); bold black-on-white reads.
    assert first["type"] == "paragraph"
    assert first["emphasis"] == "bold"
    assert first["text"] == "FROM ALICE · 14:32"
    assert out1["blocks"][1] == {"type": "paragraph", "text": "hello"}


def _png_bytes(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), color=255).save(buf, format="PNG")
    return buf.getvalue()


def test_composite_band_keeps_576_width_and_is_deterministic():
    src = _png_bytes(PRINT_HEAD_WIDTH_PX, 200)
    out1 = composite_from_band(src, sender="alice", sent_at="2026-06-03T14:32:07+00:00")
    out2 = composite_from_band(src, sender="alice", sent_at="2026-06-03T14:32:07+00:00")
    assert out1 == out2  # byte-identical -> idempotency-safe
    img = Image.open(io.BytesIO(out1))
    assert img.width == PRINT_HEAD_WIDTH_PX
    assert img.height > 200  # band added above


def test_composite_band_height_overflow_raises():
    src = _png_bytes(PRINT_HEAD_WIDTH_PX, 100)
    # band_height + image_height must stay within max_raw_height_px.
    try:
        composite_from_band(
            src, sender="alice", sent_at="2026-06-03T14:32:07+00:00",
            max_raw_height_px=120,  # 100 + band(>20) overflows
        )
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_composite_band_rejects_wrong_width():
    src = _png_bytes(500, 100)  # not 576
    try:
        composite_from_band(src, sender="alice", sent_at="2026-06-03T14:32:07+00:00")
        raised = False
    except ValueError:
        raised = True
    assert raised
