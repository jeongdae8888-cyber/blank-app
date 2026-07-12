from __future__ import annotations

from math import hypot


def pixel_distance(p1: tuple[float, float] | None, p2: tuple[float, float] | None) -> float | None:
    if p1 is None or p2 is None:
        return None
    return hypot(p2[0] - p1[0], p2[1] - p1[1])


def calibrated_distance_from_pixels(pixel_length: float | None, meters_per_pixel: float | None) -> float | None:
    if pixel_length is None or meters_per_pixel is None or meters_per_pixel <= 0:
        return None
    return pixel_length * meters_per_pixel

