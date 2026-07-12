from __future__ import annotations

from ax4u.core.avoidance_calculator import calculate_avoidance
from ax4u.core.braking_calculator import calculate_braking
from ax4u.core.models import CalculationResult
from ax4u.core.speed_calculator import calculate_speed_from_frames
from ax4u.core.time_calculator import elapsed_time_seconds, frame_delta


def analyze(
    *,
    vehicle_name: str = "",
    fps: float | None,
    speed_start_frame: int | None,
    speed_end_frame: int | None,
    measured_distance_m: float | None,
    perception_frame: int | None = None,
    braking_frame: int | None = None,
    contact_frame: int | None = None,
    reaction_time_s: float = 1.0,
    friction_coefficient: float = 0.7,
    longitudinal_grade_percent: float = 0.0,
    available_distance_m: float | None = None,
    avoidance_distance_m: float | None = None,
    lateral_distance_m: float | None = None,
) -> CalculationResult:
    result = CalculationResult(
        vehicle_name=vehicle_name,
        measurement_start_frame=speed_start_frame,
        measurement_end_frame=speed_end_frame,
        contact_frame=contact_frame,
        actual_movement_distance_m=measured_distance_m,
        distance_method="user_direct_input" if measured_distance_m is not None else "not_available",
        reaction_time_s=reaction_time_s,
        available_distance_m=available_distance_m,
    )

    speed = calculate_speed_from_frames(measured_distance_m, speed_start_frame, speed_end_frame, fps)
    result.direct_contact_speed_kmh = speed.speed_kmh
    result.perception_speed_kmh = speed.speed_kmh
    result.measurement_time_s = speed.elapsed_time_s
    result.warnings.extend(speed.warnings)
    result.basis.extend(speed.basis)

    video_gap = elapsed_time_seconds(perception_frame, braking_frame, fps)
    result.video_perception_to_braking_time_s = video_gap

    braking = calculate_braking(
        speed.speed_kmh,
        reaction_time_s,
        friction_coefficient,
        longitudinal_grade_percent,
        available_distance_m,
    )
    result.perception_distance_m = braking.perception_distance_m
    result.braking_deceleration_mps2 = braking.braking_deceleration_mps2
    result.braking_distance_m = braking.braking_distance_m
    result.stopping_distance_m = braking.stopping_distance_m
    result.residual_collision_speed_kmh = braking.residual_collision_speed_kmh
    result.avoidability = braking.avoidability
    result.warnings.extend(braking.warnings)
    result.basis.extend(braking.basis)

    if speed.speed_kmh is not None and result.residual_collision_speed_kmh is not None:
        result.calculated_contact_speed_kmh = result.residual_collision_speed_kmh
        result.contact_speed_difference_kmh = abs(speed.speed_kmh - result.residual_collision_speed_kmh)

    avoidance = calculate_avoidance(avoidance_distance_m, lateral_distance_m)
    result.avoidance_distance_m = avoidance.avoidance_distance_m
    result.lateral_distance_m = avoidance.lateral_distance_m
    result.avoidance_angle_deg = avoidance.avoidance_angle_deg
    result.warnings.extend(avoidance.warnings)
    result.basis.extend(avoidance.basis)

    result.diagnostics = {
        "FPS": fps,
        "프레임차": frame_delta(speed_start_frame, speed_end_frame),
        "측정시간": result.measurement_time_s,
        "입력 실제거리": measured_distance_m,
        "사용 실제거리": measured_distance_m if measured_distance_m and measured_distance_m > 0 else None,
        "거리 산정 방식": result.distance_method,
        "속도 계산식": speed.basis[-1] if speed.basis else "검증불가",
        "공주시간": reaction_time_s,
        "감속도": result.braking_deceleration_mps2,
        "최종 판정 이유": result.avoidability,
    }
    return result

