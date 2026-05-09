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
from printer.render.errors import RenderInputError, RenderResourceLimitError
from printer.render.typography import FontRegistry
from printer.schema.document import Document


@dataclass
class RenderContext:
    fonts: FontRegistry
    max_decoded_image_pixels: int


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
        except RenderResourceLimitError as exc:
            raise RenderResourceLimitError(
                exc.reason, block_index=index,
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


def _render_document_parts(
    doc: Document, *, fonts: FontRegistry, max_decoded_image_pixels: int,
) -> tuple[Image.Image, list[Image.Image], bool]:
    ctx = RenderContext(
        fonts=fonts,
        max_decoded_image_pixels=max_decoded_image_pixels,
    )
    preview_parts: list[Image.Image] = []
    segments: list[list[Image.Image]] = []
    current: list[Image.Image] = []
    saw_cut = False
    pending_cut = False

    for i, block in enumerate(doc.blocks):
        rendered = _render_blocks([block], ctx, base_index=i)[0]
        preview_parts.append(rendered)
        if getattr(block, "type", None) == "cut":
            saw_cut = True
            if current:
                segments.append(current)
                current = []
            pending_cut = True
        else:
            current.append(rendered)
            pending_cut = False

    if current:
        segments.append(current)

    return _stack(preview_parts), [_stack(seg) for seg in segments], saw_cut and pending_cut


def render_document_with_chunks(
    doc: Document, *, fonts: FontRegistry,
    max_decoded_image_pixels: int = 10_000_000,
) -> tuple[Image.Image, list[Image.Image], bool]:
    """Render preview and print chunks in one block-render pass."""
    return _render_document_parts(
        doc,
        fonts=fonts,
        max_decoded_image_pixels=max_decoded_image_pixels,
    )


def render_document(
    doc: Document, *, fonts: FontRegistry,
    max_decoded_image_pixels: int = 10_000_000,
) -> Image.Image:
    """Single concatenated 1-bit canvas of the entire document. Used for
    dry-run previews and single-chunk prints. ``cut`` blocks render as a
    1-px marker line — the actual hardware cut is the worker's job, driven
    by ``render_document_chunks``."""
    preview, _, _ = _render_document_parts(
        doc,
        fonts=fonts,
        max_decoded_image_pixels=max_decoded_image_pixels,
    )
    return preview


def render_document_chunks(
    doc: Document, *, fonts: FontRegistry,
    max_decoded_image_pixels: int = 10_000_000,
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
    _, chunks, trailing_cut = _render_document_parts(
        doc,
        fonts=fonts,
        max_decoded_image_pixels=max_decoded_image_pixels,
    )
    return chunks, trailing_cut
