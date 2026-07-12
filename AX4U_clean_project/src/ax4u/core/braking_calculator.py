from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt

G = 9.80665


@dataclass
class BrakingResult:
    perception_distance_m: float | None = None
    braking_deceleration_mps2: float | None = None
    braking_distance_m: float | None = None
    stopping_distance_m: float | None = None
    residual_collision_speed_kmh: float | None = None
    avoidability: str = "검증불가"
    warnings: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)


def kmh_to_mps(speed_kmh: float) -> float:
    return speed_kmh / 3.6


def mps_to_kmh(speed_mps: float) -> float:
    return speed_mps * 3.6


def effective_deceleration(friction_coefficient: float, longitudinal_grade_percent: float = 0.0) -> float:
    # Positive grade means uphill braking assistance; negative means downhill.
    grade_factor = longitudinal_grade_percent / 100.0
    return max(0.0, G * (friction_coefficient + grade_factor))


def calculate_braking(
    speed_kmh: float | None,
    reaction_time_s: float,
    friction_coefficient: float,
    longitudinal_grade_percent: float = 0.0,
    available_distance_m: float | None = None,
) -> BrakingResult:
    result = BrakingResult()
    if speed_kmh is None:
        result.warnings.append("속도 값이 없어 제동거리 계산이 불가능합니다.")
        return result
    if speed_kmh < 0:
        result.warnings.append("속도는 음수일 수 없습니다.")
        return result
    if reaction_time_s <= 0:
        result.warnings.append("공주시간은 0보다 커야 합니다.")
        return result
    if friction_coefficient <= 0:
        result.warnings.append("마찰계수는 0보다 커야 합니다.")
        return result

    speed_mps = kmh_to_mps(speed_kmh)
    decel = effective_deceleration(friction_coefficient, longitudinal_grade_percent)
    if decel <= 0:
        result.warnings.append("유효 감속도가 0 이하입니다. 마찰계수와 경사를 확인하세요.")
        return result

    perception = speed_mps * reaction_time_s
    braking = 0.0 if speed_mps == 0 else speed_mps * speed_mps / (2.0 * decel)
    stopping = perception + braking

    result.perception_distance_m = perception
    result.braking_deceleration_mps2 = decel
    result.braking_distance_m = braking
    result.stopping_distance_m = stopping
    result.basis.extend(
        [
            f"공주거리 = {speed_mps:.6g}m/s * {reaction_time_s:.6g}s = {perception:.6g}m",
            f"감속도 = {friction_coefficient:.6g} * {G:.5g} + 경사보정 = {decel:.6g}m/s^2",
            f"제동거리 = v^2 / (2a) = {braking:.6g}m",
            f"정지거리 = {perception:.6g}m + {braking:.6g}m = {stopping:.6g}m",
        ]
    )

    if available_distance_m is not None:
        braking_available = max(0.0, available_distance_m - perception)
        residual_mps = sqrt(max(0.0, speed_mps * speed_mps - 2.0 * decel * braking_available))
        residual_kmh = mps_to_kmh(residual_mps)
        result.residual_collision_speed_kmh = residual_kmh
        result.avoidability = (
            "계산상 접촉 전 정지 또는 회피 가능성이 있습니다."
            if residual_kmh <= 1.0
            else "정상 제동을 하더라도 접촉 가능성이 높습니다."
        )
        result.basis.append(
            f"잔여속도 = sqrt(max(0, v^2 - 2*a*{braking_available:.6g})) = {residual_kmh:.6g}km/h"
        )

    return result

