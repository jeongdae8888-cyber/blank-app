from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, degrees


@dataclass
class AvoidanceResult:
    avoidance_distance_m: float | None = None
    lateral_distance_m: float | None = None
    avoidance_angle_deg: float | None = None
    warnings: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)


def calculate_avoidance(longitudinal_distance_m: float | None, lateral_distance_m: float | None) -> AvoidanceResult:
    result = AvoidanceResult()
    if longitudinal_distance_m is None:
        result.warnings.append("보정된 진행방향 회피거리가 없어 회피거리 산출이 불가능합니다.")
    elif longitudinal_distance_m < 0:
        result.warnings.append("진행방향 회피거리는 음수일 수 없습니다.")
    elif longitudinal_distance_m >= 1000:
        result.warnings.append("회피거리가 1km 이상입니다. 보정 기준과 입력값을 확인하세요.")
    else:
        result.avoidance_distance_m = longitudinal_distance_m

    if lateral_distance_m is None:
        result.warnings.append("보정된 횡이동거리가 없어 회피각도 산출이 불가능합니다.")
    elif lateral_distance_m < 0:
        result.warnings.append("횡이동거리는 음수일 수 없습니다.")
    else:
        result.lateral_distance_m = lateral_distance_m

    if result.avoidance_distance_m is not None and result.lateral_distance_m is not None:
        angle = degrees(atan2(result.lateral_distance_m, result.avoidance_distance_m))
        result.avoidance_angle_deg = angle
        result.basis.append(
            f"회피각도 = atan2({result.lateral_distance_m:.6g}, {result.avoidance_distance_m:.6g}) = {angle:.6g}deg"
        )
    return result

