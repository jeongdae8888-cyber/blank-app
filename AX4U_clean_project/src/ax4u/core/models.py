from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class MarkerType(str, Enum):
    START = "start"
    PERCEPTION = "perception"
    BRAKING = "braking"
    AVOIDANCE_START = "avoidance_start"
    AVOIDANCE_END = "avoidance_end"
    CONTACT = "contact"
    SPEED_START = "speed_start"
    SPEED_END = "speed_end"


@dataclass
class VideoPoint:
    marker_type: MarkerType
    frame_index: int
    time_seconds: float
    timecode: str
    x: float
    y: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["marker_type"] = self.marker_type.value
        return data


@dataclass
class DistanceMeasurement:
    distance_m: float | None = None
    distance_method: str = "not_available"
    calibration_value: float | None = None
    confidence: str = "unknown"
    warning: str = ""


@dataclass
class SpeedMeasurement:
    start_frame: int | None = None
    end_frame: int | None = None
    fps: float | None = None
    distance_m: float | None = None


@dataclass
class BrakingInputs:
    speed_kmh: float | None
    reaction_time_s: float = 1.0
    friction_coefficient: float = 0.7
    longitudinal_grade_percent: float = 0.0


@dataclass
class AvoidanceInputs:
    longitudinal_distance_m: float | None = None
    lateral_distance_m: float | None = None


@dataclass
class CalculationResult:
    vehicle_name: str = ""
    measurement_start_frame: int | None = None
    measurement_end_frame: int | None = None
    contact_frame: int | None = None
    measurement_time_s: float | None = None
    actual_movement_distance_m: float | None = None
    distance_method: str = ""
    perception_speed_kmh: float | None = None
    direct_contact_speed_kmh: float | None = None
    calculated_contact_speed_kmh: float | None = None
    contact_speed_difference_kmh: float | None = None
    reaction_time_s: float | None = None
    video_perception_to_braking_time_s: float | None = None
    perception_distance_m: float | None = None
    braking_deceleration_mps2: float | None = None
    braking_distance_m: float | None = None
    stopping_distance_m: float | None = None
    available_distance_m: float | None = None
    residual_collision_speed_kmh: float | None = None
    avoidance_distance_m: float | None = None
    lateral_distance_m: float | None = None
    avoidance_angle_deg: float | None = None
    avoidability: str = "검증불가"
    warnings: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

