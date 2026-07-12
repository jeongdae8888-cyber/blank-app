from __future__ import annotations


def fmt_number(value: float | int | None, unit: str = "", digits: int = 2) -> str:
    if value is None:
        return "검증불가"
    return f"{value:.{digits}f}{unit}"


def fmt_frame(value: int | None) -> str:
    if value is None:
        return "미지정"
    return str(value)


def safe_float(text: str, default: float | None = None) -> float | None:
    try:
        stripped = text.strip()
        if not stripped:
            return default
        return float(stripped)
    except (TypeError, ValueError):
        return default


def safe_int(text: str, default: int | None = None) -> int | None:
    try:
        stripped = text.strip()
        if not stripped:
            return default
        return int(float(stripped))
    except (TypeError, ValueError):
        return default

