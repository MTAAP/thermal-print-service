from printer.render.blocks import renderer_for
from printer.render.renderer import RenderContext
from printer.schema.document import Document


def _ctx(fonts):
    return RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)


def test_epigraph_renders_with_indent_both_sides(fonts):
    from printer.schema.blocks import EpigraphBlock
    fn = renderer_for("epigraph")
    img = fn(EpigraphBlock(type="epigraph", text="Hello world."), _ctx(fonts))
    assert img.width == 528
    assert img.height > 0
    # First and last 40 px columns should be entirely white (the L+R indent).
    px = img.load()
    for x in (0, 10, 39):
        assert all(px[x, y] == 1 for y in range(img.height)), (
            f"column {x} has ink; epigraph should be indented from the left"
        )
    for x in (img.width - 1, img.width - 10, img.width - 40):
        assert all(px[x, y] == 1 for y in range(img.height)), (
            f"column {x} has ink; epigraph should be indented from the right"
        )


def test_epigraph_with_attribution_renders_ink_in_attribution_band(fonts):
    """The attributed version must paint ink in the additional vertical space
    it allocates — not just reserve empty pad."""
    from printer.schema.blocks import EpigraphBlock
    fn = renderer_for("epigraph")
    plain = fn(EpigraphBlock(type="epigraph", text="Hello."), _ctx(fonts))
    attributed = fn(
        EpigraphBlock(type="epigraph", text="Hello.", attribution="Anon"),
        _ctx(fonts),
    )
    assert attributed.height > plain.height
    # Attribution must paint ink in the indented column below where the plain
    # version ended. Probe x in [60, 468) (the indented text column) on rows
    # >= plain.height for at least one ink pixel.
    px = attributed.load()
    side_indent = 60
    text_end = attributed.width - side_indent
    has_attribution_ink = any(
        px[x, y] == 0
        for y in range(plain.height, attributed.height)
        for x in range(side_indent, text_end)
    )
    assert has_attribution_ink, (
        "attributed canvas allocates extra height but paints no ink — "
        "attribution may have been silently dropped"
    )
