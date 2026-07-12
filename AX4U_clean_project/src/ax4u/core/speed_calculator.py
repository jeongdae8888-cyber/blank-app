from __future__ import annotations

from dataclasses import dataclass, field

from .time_calculator import elapsed_time_seconds, frame_delta


@dataclass
class SpeedResult:
    speed_kmh: float | None
    elapsed_time_s: float | None
    frame_delta: int | None
    warnings: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)


def calculate_speed_kmh(distance_m: float | None, elapsed_time_s: float | None) -> float | None:
    if distance_m is None or elapsed_time_s is None:
        return None
    if distance_m <= 0 or elapsed_time_s <= 0:
        return None
    return distance_m / elapsed_time_s * 3.6


def calculate_speed_from_frames(
    distance_m: float | None,
    start_frame: int | None,
    end_frame: int | None,
    fps: float | None,
) -> SpeedResult:
    warnings: list[str] = []
    basis: list[str] = []
    delta = frame_delta(start_frame, end_frame)
    elapsed = elapsed_time_seconds(start_frame, end_frame, fps)

    if fps is None or fps <= 0:
        warnings.append("FPS가 0이거나 입력되지 않아 시간 계산이 불가능합니다.")
    if start_frame is None or end_frame is None:
        warnings.append("속도 측정 시작 또는 종료 프레임이 없습니다.")
    elif delta is not None and delta <= 0:
        warnings.append("속도 측정 시작 프레임과 종료 프레임이 같거나 역순입니다.")
    if distance_m is None:
        warnings.append("실제 이동거리 입력이 필요합니다.")
    elif distance_m <= 0:
        warnings.append("실제 이동거리는 0보다 커야 합니다.")

    speed = calculate_speed_kmh(distance_m, elapsed)
    if elapsed is not None:
        basis.append(f"측정시간 = ({end_frame} - {start_frame}) / {fps:g} = {elapsed:.6g}s")
    if speed is not None:
        basis.append(f"속도 = {distance_m:.6g}m / {elapsed:.6g}s * 3.6 = {speed:.6g}km/h")
        if speed > 160:
            warnings.append("산출 속도가 통상 범위를 크게 초과합니다. 거리, FPS, 프레임 지정값을 재검토하세요.")

    return SpeedResult(speed, elapsed, delta, warnings, basis)

