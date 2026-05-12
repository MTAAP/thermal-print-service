from printer.render.renderer import render_document
from printer.schema.document import Document


def test_each_rule_style_renders(fonts):
    for style in ("solid", "dashed", "dotted", "double", "wave"):
        doc = Document.model_validate({"blocks": [{"type": "rule", "style": style}]})
        img = render_document(doc, fonts=fonts)
        assert img.width == 576
        assert img.height > 0


def test_spacer_height_scales_linearly(fonts):
    doc1 = Document.model_validate({"blocks": [{"type": "spacer", "lines": 1}]})
    doc4 = Document.model_validate({"blocks": [{"type": "spacer", "lines": 4}]})
    img1 = render_document(doc1, fonts=fonts)
    img4 = render_document(doc4, fonts=fonts)
    assert img4.height == 4 * img1.height


def test_ornament_each_pattern_renders(fonts):
    for p in ("stars", "diamonds", "leaves", "geometric"):
        doc = Document.model_validate({"blocks": [{"type": "ornament", "pattern": p}]})
        img = render_document(doc, fonts=fonts)
        assert img.width == 576
        assert img.height > 0


def test_gradient_band_renders_both_directions(fonts):
    for dirn in ("down", "up"):
        doc = Document.model_validate({"blocks": [
            {"type": "gradient_band", "direction": dirn}
        ]})
        img = render_document(doc, fonts=fonts)
        assert img.width == 576
        assert img.height >= 32


def test_progress_bar_zero_and_one(fonts):
    for v in (0.0, 0.5, 1.0):
        doc = Document.model_validate({"blocks": [
            {"type": "progress_bar", "value": v, "label": f"v={v}"}
        ]})
        img = render_document(doc, fonts=fonts)
        assert img.height > 0


def test_sparkline_renders_with_values(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "sparkline",
         "values": [1.0, 5.0, 2.0, 8.0, 3.0, 7.0, 4.0],
         "label": "weather"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_sparkline_handles_flat_series(fonts):
    # All identical values — span guard prevents div-by-zero
    doc = Document.model_validate({"blocks": [
        {"type": "sparkline", "values": [5.0, 5.0, 5.0]}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


from printer.render.typography import BODY_LINE_H


def test_progress_bar_label_does_not_overlap_bar(fonts):
    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import ProgressBarBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("progress_bar")
    block = ProgressBarBlock(type="progress_bar", value=0.4, label="progressing")
    img = fn(block, ctx)
    bar_h = 16
    label_band = img.height - bar_h
    assert label_band >= BODY_LINE_H, (
        f"label band {label_band} px < BODY_LINE_H {BODY_LINE_H} px"
    )


def test_sparkline_label_does_not_overlap_bars(fonts):
    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import SparklineBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("sparkline")
    img = fn(SparklineBlock(type="sparkline", values=[1, 2, 3, 4, 5], label="spy"), ctx)
    bar_h = 32
    label_band = img.height - bar_h
    assert label_band >= BODY_LINE_H


def test_spacer_lines_matches_body_line_height(fonts):
    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import SpacerBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("spacer")
    img = fn(SpacerBlock(type="spacer", lines=3), ctx)
    assert img.height == BODY_LINE_H * 3


def test_all_ornament_patterns_render_distinct(fonts):
    from printer.render.blocks import renderer_for
    from printer.render.renderer import RenderContext
    from printer.schema.blocks import OrnamentBlock

    ctx = RenderContext(fonts=fonts, max_decoded_image_pixels=10_000_000)
    fn = renderer_for("ornament")
    patterns = ["stars", "diamonds", "leaves", "geometric", "waves", "art_deco", "minimal_dots"]
    renders = {p: fn(OrnamentBlock(type="ornament", pattern=p), ctx).tobytes() for p in patterns}
    assert len(set(renders.values())) == len(patterns)
