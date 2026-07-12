from ax4u.core.speed_calculator import calculate_speed_from_frames
from ax4u.services.analysis_service import analyze


def test_one_meter_over_ten_frames_at_30fps_is_10_8kmh():
    result = calculate_speed_from_frames(1.0, 0, 10, 30.0)
    assert result.elapsed_time_s == 10 / 30
    assert result.speed_kmh == pytest_approx(10.8)


def test_changing_distance_to_two_meters_doubles_speed():
    one = calculate_speed_from_frames(1.0, 0, 10, 30.0)
    two = calculate_speed_from_frames(2.0, 0, 10, 30.0)
    assert two.speed_kmh == pytest_approx(one.speed_kmh * 2)


def test_30fps_15_frames_is_half_second():
    result = calculate_speed_from_frames(1.0, 100, 115, 30.0)
    assert result.elapsed_time_s == pytest_approx(0.5)


def test_same_frame_is_warning_not_exception():
    result = calculate_speed_from_frames(1.0, 10, 10, 30.0)
    assert result.speed_kmh is None
    assert result.warnings


def test_distance_change_does_not_keep_old_speed():
    first = analyze(fps=30, speed_start_frame=0, speed_end_frame=10, measured_distance_m=1.0)
    second = analyze(fps=30, speed_start_frame=0, speed_end_frame=10, measured_distance_m=2.0)
    assert first.direct_contact_speed_kmh == pytest_approx(10.8)
    assert second.direct_contact_speed_kmh == pytest_approx(21.6)


def test_missing_frame_does_not_crash():
    result = calculate_speed_from_frames(1.0, None, 10, 30.0)
    assert result.speed_kmh is None
    assert any("프레임" in warning for warning in result.warnings)


def test_none_value_does_not_format_crash():
    result = calculate_speed_from_frames(None, 0, 10, 30.0)
    assert result.speed_kmh is None
    assert any("실제 이동거리" in warning for warning in result.warnings)


def test_zero_contact_speed_is_valid_number():
    result = analyze(fps=30, speed_start_frame=0, speed_end_frame=10, measured_distance_m=0.0)
    assert result.direct_contact_speed_kmh is None
    assert result.warnings


def test_missing_real_distance_does_not_create_arbitrary_speed():
    result = analyze(fps=30, speed_start_frame=0, speed_end_frame=10, measured_distance_m=None)
    assert result.direct_contact_speed_kmh is None
    assert any("실제 이동거리" in warning for warning in result.warnings)


def pytest_approx(value):
    import pytest

    return pytest.approx(value, rel=1e-6)
