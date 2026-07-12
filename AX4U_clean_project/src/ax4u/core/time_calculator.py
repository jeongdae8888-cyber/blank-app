from __future__ import annotations


def frame_delta(start_frame: int | None, end_frame: int | None) -> int | None:
    if start_frame is None or end_frame is None:
        return None
    return int(end_frame) - int(start_frame)


def elapsed_time_seconds(start_frame: int | None, end_frame: int | None, fps: float | None) -> float | None:
    delta = frame_delta(start_frame, end_frame)
    if delta is None or fps is None or fps <= 0 or delta <= 0:
        return None
    return delta / fps


def seconds_to_timecode(seconds: float | None) -> str:
    if seconds is None:
        return "검증불가"
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"

