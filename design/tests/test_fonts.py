"""All bundled fonts the @font-face block references must exist."""
from pathlib import Path

import pytest

FONT_DIR = Path(__file__).parent.parent / "tprint_design" / "fonts"

REQUIRED = [
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "NotoSansSC-Regular.otf",
]


@pytest.mark.parametrize("name", REQUIRED)
def test_required_font_present(name: str):
    p = FONT_DIR / name
    assert p.exists(), f"missing bundled font: {p}"
    assert p.stat().st_size > 1000, f"font {name} suspiciously small"
