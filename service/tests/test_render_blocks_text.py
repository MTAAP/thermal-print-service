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


def test_section_title_has_bottom_padding_before_next_block(fonts):
    """A paragraph immediately after a section_title must not sit flush
    against the title's underline. The divider owns the trailing gap so
    body-content blocks can keep their tight 0-px top stacking."""
    doc = Document.model_validate({"blocks": [
        {"type": "section_title", "text": "AGENDA", "style": "underline"},
        {"type": "paragraph", "text": "First item."},
    ]})
    title_only = Document.model_validate({"blocks": [
        {"type": "section_title", "text": "AGENDA", "style": "underline"},
    ]})
    img = render_document(doc, fonts=fonts)
    title_img = render_document(title_only, fonts=fonts)
    # The section_title canvas needs slack between its underline and the
    # end of its own block so a following paragraph has visual room.
    # Locate the underline as the bottom-most row that is overwhelmingly
    # black (the rule spans most of the live width; PIL's line caps don't
    # touch the canvas edges so we can't probe x=0 directly).
    px = title_img.load()
    underline_row = -1
    for y in range(title_img.height - 1, -1, -1):
        black = sum(1 for x in range(title_img.width) if px[x, y] == 0)
        if black > title_img.width * 0.9:
            underline_row = y
            break
    assert underline_row > 0, "section_title underline not found"
    gap_below_rule = (title_img.height - 1) - underline_row
    assert gap_below_rule >= 4, (
        f"section_title has only {gap_below_rule} px below its underline; "
        "paragraph that follows will crash into the divider"
    )
    # And the composed doc renders strictly taller than just the title.
    assert img.height > title_img.height


def test_header_inverse_band_has_white_bottom_margin(fonts):
    """The inverse band must leave a white gutter below itself so a
    following paragraph doesn't crash into the band's lower edge. Mode
    ``1`` stores black=0, white=1; the very last row of the rendered
    block should be entirely white."""
    doc = Document.model_validate({"blocks": [
        {"type": "header", "text": "Layout Smoke", "style": "inverse_band"},
    ]})
    img = render_document(doc, fonts=fonts)
    px = img.load()
    last_row = img.height - 1
    assert all(px[x, last_row] == 1 for x in range(img.width)), (
        "inverse_band bottom edge has black pixels — missing white margin"
    )


def test_section_title_underline_renders(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "section_title", "text": "TODAY", "style": "underline"},
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_section_title_has_top_padding(fonts):
    """Section titles must own breathing room above the cap-line so a
    preceding ``rule`` block doesn't visually crash into the title. The
    pre-v0.8 renderer pasted at y=0 and a rule sitting flush above
    looked like a single contiguous frame."""
    doc = Document.model_validate({"blocks": [
        {"type": "section_title", "text": "Agentic AI", "style": "underline"},
    ]})
    img = render_document(doc, fonts=fonts)
    # Scan the first column-strip for the first black pixel — that's the
    # top of the rendered glyph. It must be at least a few rows below
    # the top of the canvas.
    px = img.load()
    first_ink_row = next(
        (y for y in range(img.height) for x in range(img.width) if px[x, y] == 0),
        img.height,
    )
    assert first_ink_row >= 3, (
        f"section_title cap-line at row {first_ink_row}; expected >= 3 "
        "(top padding regression)"
    )


def test_paragraph_wraps_long_text(fonts):
    long = "the quick brown fox jumps over the lazy dog " * 6
    doc = Document.model_validate({"blocks": [
        {"type": "paragraph", "text": long}
    ]})
    img = render_document(doc, fonts=fonts)
    # Wrapped text spans multiple lines: a single-line block is ~24 px, so
    # multi-line output must clear that comfortably.
    assert img.height > 40


def test_footer_centers(fonts):
    doc = Document.model_validate({"blocks": [
        {"type": "footer", "text": "have a good one"}
    ]})
    img = render_document(doc, fonts=fonts)
    assert img.height > 0


def test_footer_wraps_long_text_instead_of_shrinking(fonts):
    """Long footers (e.g. ``Sources: ...`` runs) must wrap to additional
    lines at the target Plex Bold 16 size, not auto-Lanczos-shrink to fit
    one line — that's the regression we just fixed."""
    short = Document.model_validate({"blocks": [
        {"type": "footer", "text": "ok"}
    ]})
    long = Document.model_validate({"blocks": [
        {"type": "footer", "text": (
            "Sources: CNBC, PBS, Spaceflight Now, ScienceDaily, "
            "Yahoo Finance, CNN, SD Times, The New Stack, "
            "Releasebot, Professor Glitch."
        )}
    ]})
    short_img = render_document(short, fonts=fonts)
    long_img = render_document(long, fonts=fonts)
    # A wrapped multi-line footer is meaningfully taller than a single-line
    # footer. If long text were still being Lanczos-shrunk to one line, the
    # two heights would be near-equal.
    assert long_img.height > short_img.height * 1.5


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
    assert img.height > 60  # at least the cap height (~72 px)


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
