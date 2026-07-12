import pytest

from ax4u.core.geometry_calculator import calibrated_distance_from_pixels, pixel_distance


def test_pixel_distance():
    assert pixel_distance((0, 0), (3, 4)) == pytest.approx(5)


def test_calibrated_distance():
    assert calibrated_distance_from_pixels(20, 0.5) == pytest.approx(10)


def test_invalid_calibration_returns_none():
    assert calibrated_distance_from_pixels(20, 0) is None
