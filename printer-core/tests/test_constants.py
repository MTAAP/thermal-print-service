from printer_core.constants import (
    DPMM,
    GUTTER_PX,
    LIVE_WIDTH_PX,
    MAX_LENGTH_MM_DEFAULT,
    PRINT_HEAD_WIDTH_PX,
    mm_to_px,
    px_to_mm,
)


def test_geometry_constants_match_thermal_print_service():
    assert PRINT_HEAD_WIDTH_PX == 576
    assert GUTTER_PX == 24
    assert LIVE_WIDTH_PX == 528
    assert DPMM == 8.0
    assert MAX_LENGTH_MM_DEFAULT == 2000


def test_mm_to_px_round_trip():
    assert mm_to_px(100) == 800
    assert px_to_mm(800) == 100.0
    assert mm_to_px(0) == 0


def test_mm_to_px_rounds():
    # 1.5 mm * 8 dpmm = 12.0 px (no rounding ambiguity); 0.07 mm * 8 = 0.56 → 1
    assert mm_to_px(1.5) == 12
    assert mm_to_px(0.07) == 1
