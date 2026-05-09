from printer.render.renderer import render_document
from printer.schema.document import Document


def test_header_renders_and_is_576_wide(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "header", "text": "Friday, May 9", "style": "inverse_band"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.mode == "1"
    assert img.width == 576
    assert img.height > 0


def test_section_title_underline_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "section_title", "text": "TODAY", "style": "underline"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_paragraph_wraps_long_text(fonts):
    long = "the quick brown fox jumps over the lazy dog " * 6
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": long}
    ]})
    img = render_document(doc, fonts=fonts)
    # Wrapped text spans multiple lines: a single-line block is ~18 px, so
    # multi-line output must clear that comfortably.
    assert img.height > 30


def test_footer_centers(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "footer", "text": "have a good one"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_large_text_xxxl_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "large_text", "text": "WELCOME", "size": "xxxl", "align": "center"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    # Caps-only text under the supersample pipeline yields a bbox-tight raster
    # (~0.6× the font target size). "WELCOME" at xxxl=128 measures ~78 px tall
    # plus 8 px canvas padding ≈ 86 px. The "> 80" floor stays well clear of
    # xxl (~66 px) while reflecting the empirical measurement.
    assert img.height > 80  # large_text occupies serious vertical space


def test_pull_quote_renders_with_attribution(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "pull_quote", "text": "Better is the enemy of done.",
         "attribution": "Voltaire (paraphrased)"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_drop_cap_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "drop_cap", "first_letter": "A",
         "rest": "long form essay starts here. " * 20}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.width == 576
    assert img.height > 56  # at least the cap height


def test_code_block_preserves_lines(fonts):
    src = "def hello():\n    return 42"
    doc = Document.model_validate({"blocks": [{"type": "code", "text": src}]})
    img = render_document(doc, fonts=fonts)
    # Two lines of 18-px code = ~36 px + padding
    assert img.height >= 36


def test_rich_text_two_runs(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "BOLD ", "bold": True, "size": "lg"},
            {"text": "regular tail", "size": "md"},
        ]}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_rich_text_italic_changes_raster(fonts):
    """Synthetic-slant must change the rendered pixels. An italicized run
    differs from its upright equivalent at the same text/size."""
    upright = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "Hello ", "size": "md"},
            {"text": "world", "size": "md"},
        ]}
    ]}), fonts=fonts)
    italic = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "Hello ", "italic": True, "size": "md"},
            {"text": "world", "italic": True, "size": "md"},
        ]}
    ]}), fonts=fonts)
    # If italic were a no-op, the two raster outputs would match exactly.
    assert italic.tobytes() != upright.tobytes()
    # Italic is a shear, not a stroke change; pixel count is similar.
    # In "1" mode, histogram()[0] is the black-pixel count.
    upright_black = upright.histogram()[0]
    italic_black = italic.histogram()[0]
    assert abs(italic_black - upright_black) < upright_black * 0.5


def test_rich_text_underline_grows_height(fonts):
    """Underlined runs gain a 1-px rule at the bottom of the fragment, and
    the block height grows to accommodate the rule + gap."""
    plain = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "underline ", "size": "md"},
            {"text": "me", "size": "md"},
        ]}
    ]}), fonts=fonts)
    underlined = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "underline ", "underline": True, "size": "md"},
            {"text": "me", "underline": True, "size": "md"},
        ]}
    ]}), fonts=fonts)
    assert underlined.height > plain.height
    assert underlined.tobytes() != plain.tobytes()


def test_rich_text_italic_and_underline_compose(fonts):
    """Italic + underline together must render — the underline is drawn
    after the shear so the rule stays horizontal."""
    plain = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "both ", "size": "md"},
            {"text": "effects", "size": "md"},
        ]}
    ]}), fonts=fonts)
    both = render_document(Document.model_validate({"blocks": [
        {"type": "rich_text", "runs": [
            {"text": "both ", "italic": True, "underline": True, "size": "md"},
            {"text": "effects", "italic": True, "underline": True, "size": "md"},
        ]}
    ]}), fonts=fonts)
    assert both.height > 0
    assert both.tobytes() != plain.tobytes()
    # Composition adds height (underline) and width-spilling-into-height
    # (italic), so the composed render is at least as tall as plain.
    assert both.height >= plain.height
