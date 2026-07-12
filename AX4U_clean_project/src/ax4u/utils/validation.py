from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    ok: bool
    warnings: list[str] = field(default_factory=list)


def validate_fps(fps: float | None) -> ValidationResult:
    if fps is None or fps <= 0:
        return ValidationResult(False, ["FPS가 0이거나 입력되지 않았습니다."])
    return ValidationResult(True)


def validate_positive_distance(distance_m: float | None, label: str = "실제거리") -> ValidationResult:
    if distance_m is None:
        return ValidationResult(False, [f"{label} 입력이 필요합니다."])
    if distance_m <= 0:
        return ValidationResult(False, [f"{label}는 0보다 커야 합니다."])
    return ValidationResult(True)


def validate_frame_interval(start_frame: int | None, end_frame: int | None) -> ValidationResult:
    if start_frame is None or end_frame is None:
        return ValidationResult(False, ["프레임 지정값이 누락되었습니다."])
    if end_frame <= start_frame:
        return ValidationResult(False, ["종료 프레임은 시작 프레임보다 커야 합니다."])
    return ValidationResult(True)

