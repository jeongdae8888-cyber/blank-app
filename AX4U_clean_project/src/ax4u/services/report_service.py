from __future__ import annotations

from ax4u.core.models import CalculationResult
from ax4u.utils.formatting import fmt_frame, fmt_number


def build_text_report(result: CalculationResult) -> str:
    lines = [
        "AX4U 교통사고 영상 분석 보고서",
        "",
        f"차량명: {result.vehicle_name or '미입력'}",
        f"측정 시작 프레임: {fmt_frame(result.measurement_start_frame)}",
        f"측정 종료 프레임: {fmt_frame(result.measurement_end_frame)}",
        f"접촉 프레임: {fmt_frame(result.contact_frame)}",
        f"측정시간: {fmt_number(result.measurement_time_s, 's', 3)}",
        f"실제 이동거리: {fmt_number(result.actual_movement_distance_m, 'm', 3)}",
        f"거리 산정 방식: {result.distance_method or '검증불가'}",
        f"공주 시점 속도: {fmt_number(result.perception_speed_kmh, 'km/h', 2)}",
        f"직접 계측 접촉속도: {fmt_number(result.direct_contact_speed_kmh, 'km/h', 2)}",
        f"제동기반 환산 접촉속도: {fmt_number(result.calculated_contact_speed_kmh, 'km/h', 2)}",
        f"공주시간: {fmt_number(result.reaction_time_s, 's', 2)}",
        f"공주거리: {fmt_number(result.perception_distance_m, 'm', 3)}",
        f"제동거리: {fmt_number(result.braking_distance_m, 'm', 3)}",
        f"정지거리: {fmt_number(result.stopping_distance_m, 'm', 3)}",
        f"가용거리: {fmt_number(result.available_distance_m, 'm', 3)}",
        f"충돌지점 잔여속도: {fmt_number(result.residual_collision_speed_kmh, 'km/h', 2)}",
        f"회피거리: {fmt_number(result.avoidance_distance_m, 'm', 3)}",
        f"횡이동거리: {fmt_number(result.lateral_distance_m, 'm', 3)}",
        f"회피각도: {fmt_number(result.avoidance_angle_deg, 'deg', 2)}",
        f"회피 가능성: {result.avoidability}",
        "",
        "경고",
    ]
    lines.extend([f"- {warning}" for warning in result.warnings] or ["- 없음"])
    lines.extend(["", "계산 근거"])
    lines.extend([f"- {basis}" for basis in result.basis] or ["- 검증불가"])
    lines.extend(["", "계산 진단"])
    for key, value in result.diagnostics.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)

