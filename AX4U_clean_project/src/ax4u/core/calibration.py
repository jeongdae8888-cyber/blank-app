from __future__ import annotations

from .models import DistanceMeasurement


def choose_distance(
    user_distance_m: float | None,
    reference_pixel_length: float | None = None,
    reference_real_length_m: float | None = None,
    measured_pixel_length: float | None = None,
    lane_estimate_m: float | None = None,
) -> DistanceMeasurement:
    if user_distance_m is not None and user_distance_m > 0:
        return DistanceMeasurement(user_distance_m, "user_direct_input", user_distance_m, "high", "")

    if (
        reference_pixel_length is not None
        and reference_pixel_length > 0
        and reference_real_length_m is not None
        and reference_real_length_m > 0
        and measured_pixel_length is not None
        and measured_pixel_length > 0
    ):
        meters_per_pixel = reference_real_length_m / reference_pixel_length
        distance_m = measured_pixel_length * meters_per_pixel
        return DistanceMeasurement(distance_m, "reference_calibration", meters_per_pixel, "medium", "")

    if lane_estimate_m is not None and lane_estimate_m > 0:
        return DistanceMeasurement(
            lane_estimate_m,
            "lane_assisted_estimate",
            lane_estimate_m,
            "low",
            "차선 기반 보조 추정값입니다. 감정 판단에는 사용자 검증이 필요합니다.",
        )

    return DistanceMeasurement(None, "not_available", None, "unknown", "실제거리 입력 또는 기준거리 보정이 필요합니다.")

