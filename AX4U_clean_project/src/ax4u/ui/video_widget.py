from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel


class VideoWidget(QLabel):
    clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setText("영상을 여세요")
        self.setStyleSheet("background:#15191f;color:#d7dde5;border:1px solid #343b45;")
        self._pixmap: QPixmap | None = None
        self._points: list[tuple[float, float, str]] = []

    def set_frame(self, frame_bgr) -> None:
        if frame_bgr is None:
            return
        height, width, channels = frame_bgr.shape
        bytes_per_line = channels * width
        rgb = frame_bgr[:, :, ::-1].copy()
        image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def set_points(self, points: list[tuple[float, float, str]]) -> None:
        self._points = points
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._pixmap is not None:
            image_point = self._widget_to_image(event.position().toPoint())
            if image_point is not None:
                self.clicked.emit(image_point[0], image_point[1])
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap is None:
            return
        painter = QPainter(self)
        scaled = self._scaled_pixmap()
        top_left = self._image_top_left(scaled)
        painter.drawPixmap(top_left, scaled)
        painter.setPen(QPen(Qt.yellow, 2))
        for x, y, label in self._points:
            px = top_left.x() + x * scaled.width() / self._pixmap.width()
            py = top_left.y() + y * scaled.height() / self._pixmap.height()
            painter.drawEllipse(QPoint(int(px), int(py)), 5, 5)
            painter.drawText(int(px) + 8, int(py) - 8, label)

    def _scaled_pixmap(self) -> QPixmap:
        assert self._pixmap is not None
        return self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _image_top_left(self, scaled: QPixmap) -> QPoint:
        return QPoint((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2)

    def _widget_to_image(self, point: QPoint) -> tuple[float, float] | None:
        if self._pixmap is None:
            return None
        scaled = self._scaled_pixmap()
        top_left = self._image_top_left(scaled)
        x = point.x() - top_left.x()
        y = point.y() - top_left.y()
        if x < 0 or y < 0 or x > scaled.width() or y > scaled.height():
            return None
        return (x * self._pixmap.width() / scaled.width(), y * self._pixmap.height() / scaled.height())
