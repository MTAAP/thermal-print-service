from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from printer.constants import GUTTER_PX, LIVE_WIDTH_PX, PRINT_HEAD_WIDTH_PX

# Trigger renderer registration via side-effect imports — keep these after the
# registry import so the side-effect order is explicit and noqa-tagged.
from printer.render.blocks import embedded as _embedded  # noqa: F401
from printer.render.blocks import flow as _flow  # noqa: F401
from printer.render.blocks import lists as _lists  # noqa: F401
from printer.render.blocks import renderer_for
from printer.render.blocks import text as _text  # noqa: F401
from printer.render.blocks import visual as _visual  # noqa: F401
from printer.render.errors import RenderInputError
from printer.render.typography import FontRegistry
from printer.schema.document import Document


@dataclass
class RenderContext:
    fonts: FontRegistry


def _placeholder(message: str) -> Image.Image:
    canvas = Image.new("1", (LIVE_WIDTH_PX, 24), 1)
    d = ImageDraw.Draw(canvas)
    d.text((4, 4), message, fill=0)
    return canvas


def _render_blocks(blocks, ctx: RenderContext, *, base_index: int) -> list[Image.Image]:
    """Render a slice of blocks. ``base_index`` is the index of ``blocks[0]``
    in the parent document, used to populate ``block_index`` on
    ``RenderInputError``."""
    out: list[Image.Image] = []
    for offset, b in enumerate(blocks):
        index = base_index + offset
        block_type: str = b.type  # type: ignore[attr-defined]
        fn = renderer_for(block_type)
        if fn is None:
            out.append(_placeholder(f"[unsupported block: {block_type}]"))
            continue
        try:
            out.append(fn(b, ctx))
        except NotImplementedError:
            out.append(_placeholder(f"[unsupported block: {block_type}]"))
        except RenderInputError as exc:
            raise RenderInputError(
                str(exc), block_index=index, field=exc.field,
            ) from exc
    return out


def _stack(rendered: list[Image.Image]) -> Image.Image:
    if not rendered:
        return Image.new("1", (PRINT_HEAD_WIDTH_PX, 0), 1)
    total_h = sum(img.height for img in rendered)
    canvas = Image.new("1", (PRINT_HEAD_WIDTH_PX, total_h), 1)
    y = 0
    for img in rendered:
        if img.width == PRINT_HEAD_WIDTH_PX:
            canvas.paste(img, (0, y))
        else:
            canvas.paste(img, (GUTTER_PX, y))
        y += img.height
    return canvas


def render_document(doc: Document, *, fonts: FontRegistry) -> Image.Image:
    """Single concatenated 1-bit canvas of the entire document. Used for
    dry-run previews and single-chunk prints. ``cut`` blocks render as a
    1-px marker line — the actual hardware cut is the worker's job, driven
    by ``render_document_chunks``."""
    ctx = RenderContext(fonts=fonts)
    return _stack(_render_blocks(doc.blocks, ctx, base_index=0))


def render_document_chunks(
    doc: Document, *, fonts: FontRegistry,
) -> tuple[list[Image.Image], bool]:
    """Split the document on ``cut`` blocks into N chunks, one per
    printable segment. Returns ``(chunks, trailing_cut)``:

    - ``chunks``: list of rendered images, one per non-empty segment between
      ``cut`` boundaries. A document with no ``cut`` blocks returns a single
      chunk holding the whole document.
    - ``trailing_cut``: True if the document had at least one ``cut`` block
      with no printable content after it (e.g. ``[..., cut]`` or ``[..., cut,
      cut]``). The worker uses this to force ``auto_cut=True`` on the final
      chunk even if ``options.auto_cut`` is false — an explicit ``cut`` block
      is treated as the user's intent at that position.

    The ``cut`` block itself contributes nothing to any chunk; it is purely a
    delimiter. Empty segments (e.g. two adjacent ``cut`` blocks, or a doc
    starting with ``cut``) are dropped — the printer never receives an empty
    chunk just to cut blank paper. An all-empty doc returns ``([], False)``.
    """
    ctx = RenderContext(fonts=fonts)
    # Walk the doc, collecting non-cut blocks into segments. A segment
    # closes when a ``cut`` follows a non-empty run; consecutive cuts and
    # leading cuts collapse. Track ``pending_cut`` as "have we seen a cut
    # since the last printable block?" so the loop's tail tells us whether
    # the doc ended with a cut.
    segments: list[tuple[list, int]] = []
    current: list = []
    current_base: int | None = None
    saw_cut = False
    pending_cut = False
    for i, b in enumerate(doc.blocks):
        if getattr(b, "type", None) == "cut":
            saw_cut = True
            if current:
                assert current_base is not None
                segments.append((current, current_base))
                current = []
                current_base = None
            pending_cut = True
        else:
            if current_base is None:
                current_base = i
            current.append(b)
            pending_cut = False
    if current:
        assert current_base is not None
        segments.append((current, current_base))
    trailing_cut = saw_cut and pending_cut

    chunks: list[Image.Image] = []
    for seg, base in segments:
        rendered = _render_blocks(seg, ctx, base_index=base)
        chunks.append(_stack(rendered))
    return chunks, trailing_cut
