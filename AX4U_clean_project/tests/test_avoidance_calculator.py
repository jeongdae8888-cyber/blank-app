import pytest

from ax4u.core.avoidance_calculator import calculate_avoidance


def test_avoidance_angle():
    result = calculate_avoidance(10, 10)
    assert result.avoidance_angle_deg == pytest.approx(45.0)


def test_prevents_unchecked_one_kilometer_avoidance_distance():
    result = calculate_avoidance(1000, 2)
    assert result.avoidance_distance_m is None
    assert any("1km" in warning for warning in result.warnings)
