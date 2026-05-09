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
