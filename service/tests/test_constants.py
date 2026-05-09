from printer import constants


def test_print_head_width_is_576():
    assert constants.PRINT_HEAD_WIDTH_PX == 576


def test_live_area_geometry():
    assert constants.GUTTER_PX == 24
    assert constants.LIVE_WIDTH_PX == 528
    assert constants.LIVE_WIDTH_PX + 2 * constants.GUTTER_PX == constants.PRINT_HEAD_WIDTH_PX


def test_dpmm_is_calibrated_or_placeholder():
    assert constants.DPMM == constants.DPMM_CALIBRATED
    assert 6.5 < constants.DPMM < 8.5


def test_max_length_mm_default():
    assert constants.MAX_LENGTH_MM_DEFAULT == 2000
