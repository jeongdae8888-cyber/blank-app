from ax4u.utils.formatting import fmt_number
from ax4u.utils.validation import validate_fps, validate_frame_interval, validate_positive_distance


def test_none_format_is_safe():
    assert fmt_number(None, "km/h") == "검증불가"


def test_invalid_fps():
    assert not validate_fps(0).ok


def test_invalid_distance():
    assert not validate_positive_distance(None).ok


def test_same_frame_invalid_for_speed_interval():
    assert not validate_frame_interval(5, 5).ok
