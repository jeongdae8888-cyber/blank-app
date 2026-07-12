from __future__ import annotations

from pathlib import Path


class VideoService:
    def __init__(self) -> None:
        self.capture = None
        self.path: Path | None = None
        self.frame_count = 0
        self.fps = 0.0
        self.current_frame_index = 0

    def open(self, path: str | Path) -> bool:
        try:
            import cv2
        except ImportError:
            return False

        self.close()
        self.path = Path(path)
        self.capture = cv2.VideoCapture(str(self.path))
        if not self.capture.isOpened():
            self.close()
            return False
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.current_frame_index = 0
        return True

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
        self.capture = None
        self.path = None
        self.frame_count = 0
        self.fps = 0.0
        self.current_frame_index = 0

    def read_frame(self, frame_index: int | None = None):
        try:
            import cv2
        except ImportError:
            return None

        if self.capture is None:
            return None
        if frame_index is not None:
            frame_index = max(0, min(frame_index, max(0, self.frame_count - 1)))
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            self.current_frame_index = frame_index
        ok, frame = self.capture.read()
        if not ok:
            return None
        self.current_frame_index = int(self.capture.get(cv2.CAP_PROP_POS_FRAMES) or self.current_frame_index)
        return frame
