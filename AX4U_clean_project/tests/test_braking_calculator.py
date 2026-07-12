import pytest

from ax4u.core.braking_calculator import calculate_braking


def test_reaction_time_changes_perception_distance():
    speed = 36.0
    short = calculate_braking(speed, reaction_time_s=0.7, friction_coefficient=0.7)
    long = calculate_braking(speed, reaction_time_s=1.0, friction_coefficient=0.7)
    assert short.perception_distance_m == pytest.approx(7.0)
    assert long.perception_distance_m == pytest.approx(10.0)
    assert long.perception_distance_m > short.perception_distance_m


def test_available_distance_can_yield_stop_before_collision():
    result = calculate_braking(10.8, reaction_time_s=1.0, friction_coefficient=0.7, available_distance_m=50)
    assert result.residual_collision_speed_kmh == pytest.approx(0.0)
    assert "회피 가능성" in result.avoidability or "정지" in result.avoidability


def test_no_speed_returns_warning():
    result = calculate_braking(None, reaction_time_s=1.0, friction_coefficient=0.7)
    assert result.braking_distance_m is None
    assert result.warnings
