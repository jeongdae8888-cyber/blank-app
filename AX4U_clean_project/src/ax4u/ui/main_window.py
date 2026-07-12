from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ax4u.core.models import MarkerType, VideoPoint
from ax4u.core.time_calculator import seconds_to_timecode
from ax4u.services.analysis_service import analyze
from ax4u.services.project_service import load_project, save_project
from ax4u.services.report_service import build_text_report
from ax4u.services.video_service import VideoService
from ax4u.ui.video_widget import VideoWidget


MARKER_LABELS = {
    MarkerType.START: "시작",
    MarkerType.PERCEPTION: "공주",
    MarkerType.BRAKING: "제동",
    MarkerType.AVOIDANCE_START: "회피시작",
    MarkerType.AVOIDANCE_END: "회피끝",
    MarkerType.CONTACT: "접촉",
    MarkerType.SPEED_START: "속도시작",
    MarkerType.SPEED_END: "속도끝",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AX4U 교통사고 영상 분석기")
        self.resize(1280, 820)
        self.video = VideoService()
        self.markers: dict[MarkerType, VideoPoint] = {}
        self.active_marker: MarkerType | None = None
        self.last_result = None

        self.video_widget = VideoWidget()
        self.video_widget.clicked.connect(self._mark_active_point)
        self._build_actions()
        self._build_ui()
        self._connect_recalculate_inputs()

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        open_action = QAction("영상 열기", self)
        open_action.triggered.connect(self.open_video)
        file_menu.addAction(open_action)
        save_action = QAction("JSON 프로젝트 저장", self)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)
        load_action = QAction("JSON 프로젝트 불러오기", self)
        load_action.triggered.connect(self.load_project)
        file_menu.addAction(load_action)

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._left_panel())
        splitter.addWidget(self._right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self.video_widget)

        controls = QGridLayout()
        self.play_button = QPushButton("재생/정지")
        self.play_button.setEnabled(False)
        controls.addWidget(self.play_button, 0, 0)
        prev_button = QPushButton("이전 1프레임")
        prev_button.clicked.connect(lambda: self.goto_frame(self.frame_spin.value() - 1))
        controls.addWidget(prev_button, 0, 1)
        next_button = QPushButton("다음 1프레임")
        next_button.clicked.connect(lambda: self.goto_frame(self.frame_spin.value() + 1))
        controls.addWidget(next_button, 0, 2)
        controls.addWidget(QLabel("현재 frame"), 1, 0)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, 0)
        self.frame_spin.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.frame_spin.valueChanged.connect(self.goto_frame)
        controls.addWidget(self.frame_spin, 1, 1)
        self.timecode_label = QLabel("00:00.000")
        controls.addWidget(self.timecode_label, 1, 2)
        self.fps_label = QLabel("FPS: 0")
        controls.addWidget(self.fps_label, 1, 3)
        layout.addLayout(controls)
        return panel

    def _right_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)

        layout.addWidget(self._marker_group())
        layout.addWidget(self._input_group())
        layout.addWidget(self._result_group())
        scroll.setWidget(host)
        return scroll

    def _marker_group(self) -> QGroupBox:
        group = QGroupBox("시점 지정")
        layout = QGridLayout(group)
        self.marker_buttons: dict[MarkerType, QPushButton] = {}
        for index, marker_type in enumerate(MarkerType):
            button = QPushButton(MARKER_LABELS[marker_type])
            button.setCheckable(True)
            button.clicked.connect(lambda checked, mt=marker_type: self._select_marker(mt, checked))
            self.marker_buttons[marker_type] = button
            layout.addWidget(button, index // 2, (index % 2) * 2)
            reset = QPushButton("초기화")
            reset.clicked.connect(lambda _checked=False, mt=marker_type: self._reset_marker(mt))
            layout.addWidget(reset, index // 2, (index % 2) * 2 + 1)
        clear = QPushButton("전체 초기화")
        clear.clicked.connect(self._reset_all_markers)
        layout.addWidget(clear, 4, 0, 1, 4)
        return group

    def _input_group(self) -> QGroupBox:
        group = QGroupBox("계산 입력")
        form = QFormLayout(group)
        self.vehicle_name = QLineEdit()
        form.addRow("차량명", self.vehicle_name)
        self.fps_input = self._double_spin(0, 240, 30, 3)
        form.addRow("FPS", self.fps_input)
        self.distance_input = self._double_spin(0, 10000, 1.0, 3)
        form.addRow("실제 이동거리(m)", self.distance_input)
        self.speed_start_input = self._spin(0, 999999, 0)
        form.addRow("속도 시작 프레임", self.speed_start_input)
        self.speed_end_input = self._spin(0, 999999, 10)
        form.addRow("속도 종료 프레임", self.speed_end_input)
        self.use_contact_as_speed_end = QCheckBox("접촉 프레임을 속도 종료로 사용")
        form.addRow("", self.use_contact_as_speed_end)
        self.reaction_time_input = self._double_spin(0.1, 3.0, 1.0, 1)
        self.reaction_time_input.setSingleStep(0.1)
        form.addRow("공주시간(s)", self.reaction_time_input)
        self.friction_input = self._double_spin(0.01, 2.0, 0.7, 2)
        form.addRow("마찰계수", self.friction_input)
        self.grade_input = self._double_spin(-30, 30, 0, 2)
        form.addRow("종단경사(%)", self.grade_input)
        self.available_distance_input = self._double_spin(0, 10000, 0, 3)
        form.addRow("가용거리(m)", self.available_distance_input)
        self.avoidance_distance_input = self._double_spin(0, 10000, 0, 3)
        form.addRow("회피거리(m)", self.avoidance_distance_input)
        self.lateral_distance_input = self._double_spin(0, 10000, 0, 3)
        form.addRow("횡이동거리(m)", self.lateral_distance_input)
        calculate_button = QPushButton("계산")
        calculate_button.clicked.connect(self.calculate)
        form.addRow(calculate_button)
        return group

    def _result_group(self) -> QGroupBox:
        group = QGroupBox("결과 및 진단")
        layout = QVBoxLayout(group)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        layout.addWidget(self.result_text, 1)
        row = QHBoxLayout()
        copy_button = QPushButton("보고서 복사")
        copy_button.clicked.connect(self.copy_report)
        row.addWidget(copy_button)
        csv_button = QPushButton("CSV 저장")
        csv_button.clicked.connect(self.save_csv)
        row.addWidget(csv_button)
        layout.addLayout(row)
        return group

    def _double_spin(self, minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin

    def _spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _connect_recalculate_inputs(self) -> None:
        for widget in [
            self.fps_input,
            self.distance_input,
            self.speed_start_input,
            self.speed_end_input,
            self.reaction_time_input,
            self.friction_input,
            self.grade_input,
            self.available_distance_input,
            self.avoidance_distance_input,
            self.lateral_distance_input,
        ]:
            widget.valueChanged.connect(self.calculate)
        self.vehicle_name.textChanged.connect(self.calculate)
        self.use_contact_as_speed_end.stateChanged.connect(self.calculate)

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "영상 열기", "", "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)")
        if not path:
            return
        if not self.video.open(path):
            QMessageBox.warning(self, "영상 오류", "영상 파일을 열 수 없습니다.")
            return
        self.frame_spin.setRange(0, max(0, self.video.frame_count - 1))
        if self.video.fps > 0:
            self.fps_input.setValue(self.video.fps)
        self.fps_label.setText(f"FPS: {self.video.fps:.3f}")
        self.goto_frame(0)

    def goto_frame(self, frame_index: int) -> None:
        if self.video.capture is None:
            return
        frame = self.video.read_frame(frame_index)
        if frame is not None:
            self.video_widget.set_frame(frame)
            self.frame_spin.blockSignals(True)
            self.frame_spin.setValue(frame_index)
            self.frame_spin.blockSignals(False)
            fps = self.fps_input.value()
            self.timecode_label.setText(seconds_to_timecode(frame_index / fps if fps > 0 else None))
            self._refresh_overlay()

    def _select_marker(self, marker_type: MarkerType, checked: bool) -> None:
        for other, button in self.marker_buttons.items():
            if other != marker_type:
                button.setChecked(False)
        self.active_marker = marker_type if checked else None

    def _mark_active_point(self, x: float, y: float) -> None:
        if self.active_marker is None:
            return
        frame = self.frame_spin.value()
        fps = self.fps_input.value()
        seconds = frame / fps if fps > 0 else 0.0
        point = VideoPoint(self.active_marker, frame, seconds, seconds_to_timecode(seconds), x, y)
        self.markers[self.active_marker] = point
        self.marker_buttons[self.active_marker].setChecked(True)
        self._apply_marker_to_inputs(self.active_marker, frame)
        self._refresh_overlay()
        self.calculate()

    def _apply_marker_to_inputs(self, marker_type: MarkerType, frame: int) -> None:
        if marker_type == MarkerType.SPEED_START:
            self.speed_start_input.setValue(frame)
        elif marker_type == MarkerType.SPEED_END:
            self.speed_end_input.setValue(frame)
        elif marker_type == MarkerType.CONTACT and self.use_contact_as_speed_end.isChecked():
            self.speed_end_input.setValue(frame)

    def _reset_marker(self, marker_type: MarkerType) -> None:
        self.markers.pop(marker_type, None)
        self.marker_buttons[marker_type].setChecked(False)
        if self.active_marker == marker_type:
            self.active_marker = None
        self._refresh_overlay()
        self.calculate()

    def _reset_all_markers(self) -> None:
        self.markers.clear()
        for button in self.marker_buttons.values():
            button.setChecked(False)
        self.active_marker = None
        self._refresh_overlay()
        self.calculate()

    def _refresh_overlay(self) -> None:
        points = [(point.x, point.y, MARKER_LABELS[point.marker_type]) for point in self.markers.values()]
        self.video_widget.set_points(points)

    def calculate(self) -> None:
        available = self.available_distance_input.value() or None
        avoidance = self.avoidance_distance_input.value() or None
        lateral = self.lateral_distance_input.value() or None
        contact = self.markers.get(MarkerType.CONTACT)
        perception = self.markers.get(MarkerType.PERCEPTION)
        braking = self.markers.get(MarkerType.BRAKING)
        speed_end = contact.frame_index if self.use_contact_as_speed_end.isChecked() and contact else self.speed_end_input.value()
        self.last_result = analyze(
            vehicle_name=self.vehicle_name.text(),
            fps=self.fps_input.value(),
            speed_start_frame=self.speed_start_input.value(),
            speed_end_frame=speed_end,
            measured_distance_m=self.distance_input.value() or None,
            perception_frame=perception.frame_index if perception else None,
            braking_frame=braking.frame_index if braking else None,
            contact_frame=contact.frame_index if contact else None,
            reaction_time_s=self.reaction_time_input.value(),
            friction_coefficient=self.friction_input.value(),
            longitudinal_grade_percent=self.grade_input.value(),
            available_distance_m=available,
            avoidance_distance_m=avoidance,
            lateral_distance_m=lateral,
        )
        self.result_text.setPlainText(build_text_report(self.last_result))

    def copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.result_text.toPlainText())

    def save_csv(self) -> None:
        if self.last_result is None:
            self.calculate()
        path, _ = QFileDialog.getSaveFileName(self, "CSV 저장", "ax4u_result.csv", "CSV Files (*.csv)")
        if not path:
            return
        data = self.last_result.to_dict()
        with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["field", "value"])
            for key, value in data.items():
                writer.writerow([key, value])

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "JSON 프로젝트 저장", "ax4u_project.json", "JSON Files (*.json)")
        if not path:
            return
        save_project(path, self._project_data())

    def load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "JSON 프로젝트 불러오기", "", "JSON Files (*.json)")
        if not path:
            return
        data = load_project(path)
        inputs = data.get("inputs", {})
        self.vehicle_name.setText(inputs.get("vehicle_name", ""))
        self.fps_input.setValue(float(inputs.get("fps", 30)))
        self.distance_input.setValue(float(inputs.get("distance_m", 1)))
        self.speed_start_input.setValue(int(inputs.get("speed_start_frame", 0)))
        self.speed_end_input.setValue(int(inputs.get("speed_end_frame", 10)))
        self.reaction_time_input.setValue(float(inputs.get("reaction_time_s", 1)))
        self.friction_input.setValue(float(inputs.get("friction_coefficient", 0.7)))
        self.grade_input.setValue(float(inputs.get("grade_percent", 0)))
        self.available_distance_input.setValue(float(inputs.get("available_distance_m", 0)))
        self.avoidance_distance_input.setValue(float(inputs.get("avoidance_distance_m", 0)))
        self.lateral_distance_input.setValue(float(inputs.get("lateral_distance_m", 0)))
        self.markers.clear()
        for item in data.get("markers", []):
            marker = MarkerType(item["marker_type"])
            self.markers[marker] = VideoPoint(
                marker,
                int(item["frame_index"]),
                float(item["time_seconds"]),
                item["timecode"],
                float(item["x"]),
                float(item["y"]),
            )
        self._refresh_overlay()
        self.calculate()

    def _project_data(self) -> dict:
        return {
            "inputs": {
                "vehicle_name": self.vehicle_name.text(),
                "fps": self.fps_input.value(),
                "distance_m": self.distance_input.value(),
                "speed_start_frame": self.speed_start_input.value(),
                "speed_end_frame": self.speed_end_input.value(),
                "reaction_time_s": self.reaction_time_input.value(),
                "friction_coefficient": self.friction_input.value(),
                "grade_percent": self.grade_input.value(),
                "available_distance_m": self.available_distance_input.value(),
                "avoidance_distance_m": self.avoidance_distance_input.value(),
                "lateral_distance_m": self.lateral_distance_input.value(),
            },
            "markers": [point.to_dict() for point in self.markers.values()],
            "result": self.last_result.to_dict() if self.last_result else None,
        }
