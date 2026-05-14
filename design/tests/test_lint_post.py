from PIL import Image

from tprint_design.lint_post import post_render_lint


def _white(w: int, h: int) -> Image.Image:
    return Image.new("L", (w, h), 255)


def _color(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    for y in range(h):
        for x in range(w):
            img.putpixel((x, y), (200, 50, 50))  # solid red
    return img


def test_color_usage_flagged_as_error():
    findings = post_render_lint(rgb=_color(10, 10), one_bit=Image.new("1", (10, 10), 1),
                                effective_max_length_mm=2000)
    assert any(f.rule == "color_used" and f.severity.value == "error" for f in findings)


def test_mostly_empty_render_warns():
    findings = post_render_lint(rgb=_white(576, 200).convert("RGB"),
                                one_bit=Image.new("1", (576, 200), 1),
                                effective_max_length_mm=2000)
    assert any(f.rule == "mostly_empty" for f in findings)


def test_height_over_max_length_errors():
    # 1 mm = 8 px → 100 mm = 800 px. Cap at 50 mm → render of 600 px (75 mm)
    # exceeds the cap.
    img = Image.new("1", (576, 600), 0)  # all-black so mostly_empty doesn't fire
    findings = post_render_lint(rgb=Image.new("RGB", (576, 600), (0, 0, 0)),
                                one_bit=img,
                                effective_max_length_mm=50)
    assert any(f.rule == "max_length_exceeded" and f.severity.value == "error"
               for f in findings)


def test_height_over_5m_warns():
    img = Image.new("1", (576, 41000), 0)
    findings = post_render_lint(rgb=Image.new("RGB", (576, 41000), (0, 0, 0)),
                                one_bit=img,
                                effective_max_length_mm=10000)
    assert any(f.rule == "very_long_print" and f.severity.value == "warning"
               for f in findings)


def test_clean_render_produces_no_findings():
    # 50% black: not empty, not over length.
    img = Image.new("1", (576, 200), 0)
    for y in range(0, 200, 2):
        for x in range(576):
            img.putpixel((x, y), 1)  # white stripe every other row
    findings = post_render_lint(rgb=Image.new("RGB", (576, 200), (0, 0, 0)),
                                one_bit=img,
                                effective_max_length_mm=2000)
    assert findings == []
