from printer.render.typography import supersample_render


def test_registry_loads_all_three_families(fonts):
    body = fonts.body()
    display_medium = fonts.display(weight="medium")
    display_bold = fonts.display(weight="bold")
    code = fonts.code()
    assert body is not None
    assert display_medium is not None
    assert display_bold is not None
    assert code is not None


def test_supersample_outputs_1bit_within_max_width(fonts):
    img = supersample_render(
        text="Hello",
        font=fonts.display(weight="medium", size_px=24),
        target_size_px=24,
        max_width_px=400,
    )
    assert img.mode == "1"
    assert img.width <= 400


def test_supersample_handles_long_text_by_capping_width(fonts):
    long_text = "the quick brown fox jumps over the lazy dog several times"
    img = supersample_render(
        text=long_text,
        font=fonts.display(weight="medium", size_px=32),
        target_size_px=32,
        max_width_px=200,
    )
    assert img.width == 200


def test_prose_font_is_plex_sans_medium(fonts):
    from pathlib import Path
    p = Path(fonts.prose().path)
    assert "Plex" in p.name and "Medium" in p.name


def test_render_prose_line_returns_paste_able_image(fonts):
    from printer.render.typography import render_prose_line
    img = render_prose_line("hello world", fonts=fonts, max_width_px=400)
    assert img.mode == "1"
    assert img.width > 0 and img.height > 0


def test_prose_atom_width_is_proportional(fonts):
    """Proportional font: 'm' is much wider than 'i'."""
    wi = fonts.prose_atom_width("iiii")
    wm = fonts.prose_atom_width("mmmm")
    assert wm > wi + 8
