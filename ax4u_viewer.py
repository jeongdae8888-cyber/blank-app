# blackbox_viewer_speed_mvp_v16.py
# 블랙박스 판독 MVP v1.9
# 구조:
#   A = 시작시점 1개 버튼으로 동시 저장
#       - 도로 기준 시작시점
#       - 차량 시작시점
#       - 시작 프레임/시간
#
#   B = 접촉지점
#       - 차량이 실제로 도달한 종료 위치
#       - 종료 프레임/시간
#
#   C = 피양 후점
#       - 도로 기준 종료 위치
#       - 시작-접촉거리 기준점
#
# 산출:
#   - 시작-접촉거리 기준
#   - 시작→접촉 차량 추정거리
#   - 시작→접촉 기준축 대비 시작→접촉 진행각
#   - 횡이동거리
#   - 차량추정속도
#
# 설치:
#   py -3.13 -m pip install PySide6 opencv-python
#
# 실행:
#   py -3.13 blackbox_viewer_speed_mvp_v16.py

import csv
import hashlib
import html
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QObject, QThread
    from PySide6.QtGui import QImage, QPixmap, QAction
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDoubleSpinBox,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QTextBrowser,
    QPushButton,
        QSlider,
        QSpinBox,
        QSplitter,
        QScrollArea,
        QGridLayout,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem, QHeaderView,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    print("[필수 모듈 없음]")
    print("아래 명령어로 설치하세요:")
    print("  py -3.13 -m pip install PySide6 opencv-python")
    raise


APP_NAME = "AX4U 교통사고 영상 판독기"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"}
VEHICLES = ["자차", "상대차", "기타"]
EVENT_TYPES = [
    "상대차량 최초 확인",
    "자차 위험인지",
    "자차 제동/감속",
    "상대차량 차선침범",
    "신호 변경",
    "접촉",
    "최종 정지",
    "기타",
]


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def seconds_to_timecode(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    return ("".join("_" if c in bad else c for c in name).strip()) or "blackbox_case"


def make_frame_point(frame_index: int, fps: float, x: int, y: int) -> dict:
    """프레임/시간과 좌표를 함께 저장."""
    sec = frame_index / fps if fps else 0.0
    return {
        "frame": int(frame_index),
        "time_seconds": float(sec),
        "timecode": seconds_to_timecode(sec),
        "x": int(x),
        "y": int(y),
    }


def make_position_only(frame_index: int, fps: float, x: int, y: int) -> dict:
    """위치 기준점. 프레임/시간도 함께 기록한다."""
    sec = frame_index / fps if fps else 0.0
    return {
        "frame": int(frame_index),
        "time_seconds": float(sec),
        "timecode": seconds_to_timecode(sec),
        "marked_frame": int(frame_index),
        "marked_timecode": seconds_to_timecode(sec),
        "x": int(x),
        "y": int(y),
    }


def point_text(p):
    if not p:
        return "미지정"
    if "frame" in p:
        return f"F{p['frame']} {p['timecode']} ({p['x']},{p['y']})"
    if "marked_frame" in p:
        return f"F{p['marked_frame']} {p['marked_timecode']} ({p['x']},{p['y']})"
    return f"({p['x']},{p['y']})"

def pixel_distance(p1, p2) -> float:
    if not p1 or not p2:
        return 0.0
    return math.hypot(float(p2["x"]) - float(p1["x"]), float(p2["y"]) - float(p1["y"]))



class VideoLabel(QLabel):
    image_clicked = Signal(int, int)
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(760, 430)
        self.setText("영상 파일을 열거나\n창 안으로 드래그앤드롭하세요.")
        self.setStyleSheet(
            "QLabel { background-color: #111; color: #ddd; border: 1px solid #444; font-size: 16px; }"
        )
        self.source_w = 0
        self.source_h = 0

    def set_source_size(self, w: int, h: int):
        self.source_w = int(w)
        self.source_h = int(h)

    def _path_from_event(self, event):
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                return str(path)
        return None

    def dragEnterEvent(self, event):
        path = self._path_from_event(event)
        if path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        path = self._path_from_event(event)
        if path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._path_from_event(event)
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if self.source_w <= 0 or self.source_h <= 0:
            return

        label_w = self.width()
        label_h = self.height()
        scale = min(label_w / self.source_w, label_h / self.source_h)
        disp_w = self.source_w * scale
        disp_h = self.source_h * scale
        off_x = (label_w - disp_w) / 2
        off_y = (label_h - disp_h) / 2

        x = event.position().x()
        y = event.position().y()

        if x < off_x or x > off_x + disp_w or y < off_y or y > off_y + disp_h:
            return

        src_x = int(round((x - off_x) / scale))
        src_y = int(round((y - off_y) / scale))
        src_x = max(0, min(src_x, self.source_w - 1))
        src_y = max(0, min(src_y, self.source_h - 1))
        self.image_clicked.emit(src_x, src_y)



class LaneCountWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, video_path, start_f, end_f, fps, p1, p2, cycle_len, extra_m, min_speed_kmh=60.0, max_speed_kmh=160.0):
        super().__init__()
        self.video_path = video_path
        self.start_f = int(start_f)
        self.end_f = int(end_f)
        self.fps = float(fps) if fps else 30.0
        self.p1 = dict(p1) if p1 else {}
        self.p2 = dict(p2) if p2 else {}
        self.cycle_len = float(cycle_len)
        self.extra_m = float(extra_m)
        self.min_speed_kmh = float(min_speed_kmh)
        self.max_speed_kmh = float(max_speed_kmh)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def lane_mask(self, frame):
        """
        영상 하단 도로영역에서 흰색/노란색/흐린 회색 차선표시 후보를 만든다.

        v6.7 보정:
        - 흐리고 끊긴 차선이 흰색 임계값에 걸리지 않는 문제 보정
        - CLAHE 대비강화 + Top-hat 밝은 선분 검출 + Canny edge를 보조로 사용
        - 자동계수가 노이즈를 차선으로 착각해 비정상 고속값을 내는 경우는 run()에서 별도 차단
        """
        h, w = frame.shape[:2]

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hh, ss, vv = cv2.split(hsv)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1) 기본 흰색/노란색 차선
        white_strong = ((vv > 145) & (ss < 145)) | (gray > 180)
        white_soft = ((vv > 105) & (ss < 95) & (gray > 105))
        yellow = ((hh >= 12) & (hh <= 48) & (ss > 40) & (vv > 80))

        # 2) 흐린 회색 차선 대비 강화
        clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
        eq = clahe.apply(gray)

        # 국부적으로 주변보다 밝은 선분을 잡는다.
        bg = cv2.GaussianBlur(eq, (0, 0), 7)
        local_bright = cv2.subtract(eq, bg)
        _, local_mask = cv2.threshold(local_bright, 10, 255, cv2.THRESH_BINARY)

        # Top-hat: 어두운 도로 위의 얇은 밝은 차선 조각 검출
        tophat_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        tophat = cv2.morphologyEx(eq, cv2.MORPH_TOPHAT, tophat_kernel)
        _, tophat_mask = cv2.threshold(tophat, 9, 255, cv2.THRESH_BINARY)

        # 3) 차선 가장자리 후보
        edges = cv2.Canny(eq, 45, 130)

        mask = (
            white_strong.astype(np.uint8) * 255
            | white_soft.astype(np.uint8) * 255
            | yellow.astype(np.uint8) * 255
            | local_mask
            | tophat_mask
            | edges
        )

        # 도로 하단 ROI
        roi = np.zeros_like(mask)
        y1 = int(h * 0.42)
        y2 = int(h * 0.94)
        x1 = int(w * 0.04)
        x2 = int(w * 0.96)
        roi[y1:y2, x1:x2] = 255
        mask = cv2.bitwise_and(mask, roi)

        # 점노이즈 제거 후 끊긴 차선 조각을 약하게 연결
        open_kernel = np.ones((2, 2), np.uint8)
        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)

        return mask


    def sample_band_score(self, mask, x1_ratio, x2_ratio, y_ratio):
        h, w = mask.shape[:2]
        y = int(h * y_ratio)
        band_h = max(5, int(h * 0.014))
        y1 = max(0, y - band_h)
        y2 = min(h, y + band_h)
        x1 = int(w * x1_ratio)
        x2 = int(w * x2_ratio)
        band = mask[y1:y2, x1:x2]
        if band.size == 0:
            return 0.0
        return float(np.count_nonzero(band)) / float(band.size)

    def lane_line_score(self, frame, mask):
        """
        프레임 1장에서 실제 차선 '선분'이 보이는 정도를 산출한다.

        기존 픽셀면적 방식은 빈 도로/노이즈도 점수화해서 0 또는 전투기속도 문제가 생겼다.
        이 함수는 HoughLinesP로 길이·각도 조건을 만족하는 선분만 차선 후보로 본다.
        """
        h, w = frame.shape[:2]

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        eq = clahe.apply(gray)

        # 하단 도로영역만 사용
        roi = np.zeros_like(eq)
        y1 = int(h * 0.42)
        y2 = int(h * 0.95)
        x1 = int(w * 0.04)
        x2 = int(w * 0.96)
        roi[y1:y2, x1:x2] = 255

        # mask + edge를 같이 사용하되, 실제 선분 검출은 edge 기반
        edges1 = cv2.Canny(eq, 35, 115)
        edges2 = cv2.Canny(mask, 30, 100)
        edges = cv2.bitwise_or(edges1, edges2)
        edges = cv2.bitwise_and(edges, roi)

        # 끊긴 차선 선분 연결
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k, iterations=1)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180.0,
            threshold=18,
            minLineLength=max(12, int(w * 0.025)),
            maxLineGap=max(8, int(w * 0.018)),
        )

        if lines is None:
            return 0.0, {"line_count": 0, "max_len": 0.0, "total_len": 0.0}

        total_len = 0.0
        max_len = 0.0
        count = 0

        # 차선 선분은 대체로 수평선보다 사선/세로 방향으로 잡힌다.
        # 너무 수평인 선은 노면 경계/그림자일 가능성이 높아 제외.
        for line in lines[:, 0, :]:
            xA, yA, xB, yB = [float(v) for v in line]
            if yA < y1 or yB < y1:
                continue

            dx = xB - xA
            dy = yB - yA
            length = math.hypot(dx, dy)
            if length < 10:
                continue

            angle = abs(math.degrees(math.atan2(dy, dx)))
            if angle > 90:
                angle = 180 - angle

            # 12도 미만: 거의 수평선, 도로 경계/노이즈 가능성
            # 88도 초과도 세로 노이즈 가능성이 있어 약하게만 허용
            if angle < 12:
                continue

            # 너무 두껍거나 화면 가장자리의 구조물성 선분은 감점
            mid_x = (xA + xB) / 2.0
            mid_y = (yA + yB) / 2.0
            if mid_y < y1 or mid_y > y2:
                continue
            if mid_x < x1 or mid_x > x2:
                continue

            # 선분 주변 밝기가 주변보다 약간이라도 밝은지 확인
            x_min = int(max(0, min(xA, xB) - 3))
            x_max = int(min(w, max(xA, xB) + 4))
            y_min = int(max(0, min(yA, yB) - 3))
            y_max = int(min(h, max(yA, yB) + 4))
            patch = eq[y_min:y_max, x_min:x_max]
            if patch.size == 0:
                continue

            local_mean = float(np.mean(patch))
            road_patch = eq[y1:y2, x1:x2]
            road_med = float(np.median(road_patch)) if road_patch.size else 0.0

            # 흐린 회색 차선도 살리되, 완전한 빈 노면은 제외
            brightness_bonus = max(0.0, local_mean - road_med)
            if brightness_bonus < 1.5 and length < 18:
                continue

            weight = 1.0
            if 18 <= angle <= 78:
                weight *= 1.25
            if brightness_bonus > 8:
                weight *= 1.20

            total_len += length * weight
            max_len = max(max_len, length)
            count += 1

        if count == 0:
            return 0.0, {"line_count": 0, "max_len": 0.0, "total_len": 0.0}

        # 점수는 선분 길이와 개수를 함께 반영한다. 빈 공간은 0점.
        score = (total_len / max(1.0, float(w))) + count * 0.018 + max_len / max(1.0, float(w)) * 0.35
        return float(score), {"line_count": int(count), "max_len": float(max_len), "total_len": float(total_len)}

    def count_peaks_from_scores(self, scores, frames, step):
        if len(scores) < 10:
            return [], {}

        arr = np.array(scores, dtype=np.float32)

        win = max(3, min(15, int(round(0.10 * self.fps / max(step, 1)))))
        kernel = np.ones(win, dtype=np.float32) / float(win)
        smooth = np.convolve(arr, kernel, mode="same")

        med = float(np.median(smooth))
        p75 = float(np.percentile(smooth, 75))
        p88 = float(np.percentile(smooth, 88))
        p95 = float(np.percentile(smooth, 95))
        std = float(np.std(smooth))
        threshold = max(med + std * 0.55, (p75 + p95) / 2.2, p88 * 0.72)

        binary = smooth > threshold

        min_gap = max(1, int(round(0.05 * self.fps / max(step, 1))))
        i = 0
        while i < len(binary):
            if binary[i]:
                i += 1
                continue
            j = i
            while j < len(binary) and not binary[j]:
                j += 1
            if i > 0 and j < len(binary) and (j - i) <= min_gap:
                binary[i:j] = True
            i = j

        min_high = max(1, int(round(0.035 * self.fps / max(step, 1))))
        segments = []
        i = 0
        while i < len(binary):
            if not binary[i]:
                i += 1
                continue

            j = i
            while j < len(binary) and binary[j]:
                j += 1

            if (j - i) >= min_high:
                peak = int(i + np.argmax(smooth[i:j]))
                segments.append((i, j, frames[peak], float(smooth[peak])))

            i = j

        meta = {
            "median_score": med,
            "p75_score": p75,
            "p88_score": p88,
            "p95_score": p95,
            "std_score": std,
            "threshold": float(threshold),
        }
        return segments, meta

    def estimate_period_by_autocorr(self, scores_by_region, frames, step):
        """
        차선 1주기 반복성을 자기상관으로 찾는다.

        v3.5 문제:
        실제 1주기 lag가 7프레임인데 자기상관이 14프레임, 즉 2주기 반복을 더 강하게 잡으면
        거리와 속도가 절반으로 떨어진다. 100km/h급이 49km/h로 나오는 원인이 이것이다.

        v3.6:
        가장 강한 lag를 바로 쓰지 않고, 그 lag의 1/2, 1/3, 1/4 위치에 충분한 반복성이 있으면
        더 짧은 기본주기(fundamental)를 채택한다.
        """
        if not frames:
            return None

        total_frames = max(1, self.end_f - self.start_f)

        # 현실 속도범위로 lag 검색구간을 제한한다.
        # speed = cycle_len * fps * 3.6 / lag
        # lag = cycle_len * fps * 3.6 / speed
        speed_max = max(10.0, float(self.max_speed_kmh))
        speed_min = max(1.0, float(self.min_speed_kmh))
        if speed_min >= speed_max:
            speed_min, speed_max = 60.0, 160.0

        min_lag_by_speed = int(math.ceil(self.cycle_len * self.fps * 3.6 / speed_max))
        max_lag_by_speed = int(math.floor(self.cycle_len * self.fps * 3.6 / speed_min))

        min_lag = max(3, min_lag_by_speed)
        max_lag = max(min_lag + 2, max_lag_by_speed)
        max_lag = min(max_lag, len(frames) // 2)

        if max_lag <= min_lag:
            max_lag = min(len(frames) // 2, min_lag + 8)

        best = None

        for region, scores in scores_by_region.items():
            arr = np.array(scores, dtype=np.float32)
            if arr.size < max_lag + 5:
                continue

            # 느린 밝기 변화 제거
            trend_win = max(15, min(55, int(round(self.fps * 1.2))))
            kernel = np.ones(trend_win, dtype=np.float32) / float(trend_win)
            trend = np.convolve(arr, kernel, mode="same")
            hp = arr - trend
            hp = hp - float(np.mean(hp))

            energy = float(np.dot(hp, hp))
            if energy <= 1e-9:
                continue

            ac = np.correlate(hp, hp, mode="full")[len(hp) - 1:]
            ac0 = float(ac[0])
            if ac0 <= 1e-9:
                continue

            raw_corr = {}
            scored = []
            for lag in range(min_lag, max_lag + 1):
                corr0 = float(ac[lag] / ac0)
                raw_corr[lag] = corr0

                # 예상속도.
                # v6.7: 너무 비현실적인 주기는 감점이 아니라 후보에서 제외한다.
                # 흐린 차선을 못 잡으면 2~3프레임짜리 노이즈가 반복주기로 잡혀 300km/h 이상이 나올 수 있다.
                implied_speed_kmh = self.cycle_len * self.fps * 3.6 / float(lag)

                hard_min_speed = max(5.0, self.min_speed_kmh * 0.45)
                hard_max_speed = max(self.max_speed_kmh * 1.25, self.max_speed_kmh + 40.0)
                if implied_speed_kmh < hard_min_speed or implied_speed_kmh > hard_max_speed:
                    continue

                score = corr0
                if self.min_speed_kmh <= implied_speed_kmh <= self.max_speed_kmh:
                    score *= 1.75
                    # 80~130km/h는 이번 유형의 속도 산정에서 우선 후보로 본다.
                    if 80 <= implied_speed_kmh <= 130:
                        score *= 1.30
                else:
                    score *= 0.35

                # 2~3F는 프레임 노이즈 가능성이 커서 약간 감점.
                if lag < 4:
                    score *= 0.75

                scored.append((score, lag, corr0, implied_speed_kmh))

            if not scored:
                continue

            score, lag, corr, implied_speed = max(scored, key=lambda x: x[0])

            if corr < 0.08:
                continue

            original_lag = lag
            original_corr = corr
            harmonic_divisor = 1
            harmonic_note = "원주기"

            # 핵심: 2주기/3주기/4주기 고조파를 기본주기로 잘못 잡은 경우 보정.
            # 예: lag 14F가 가장 강하지만 lag 7F에도 충분한 상관이 있으면 7F를 채택.
            best_short = None
            for divisor in (2, 3, 4):
                cand_lag = int(round(original_lag / divisor))
                if cand_lag < min_lag or cand_lag < 3:
                    continue
                if cand_lag not in raw_corr:
                    continue

                cand_corr = float(raw_corr[cand_lag])
                cand_speed = self.cycle_len * self.fps * 3.6 / float(cand_lag)

                # 조건:
                # - 짧은 주기의 상관이 원래 lag의 일정 비율 이상
                # - 속도도 현실범위 안에 있으면 적극 채택
                # 긴 주기 선택으로 49km/h처럼 반토막 나는 경우를 막기 위해
                # 짧은 기본주기의 상관이 약해도 현실 속도범위 안이면 더 적극적으로 채택한다.
                enough_corr = cand_corr >= max(0.025, original_corr * 0.20)
                plausible_speed = self.min_speed_kmh <= cand_speed <= self.max_speed_kmh

                if enough_corr and plausible_speed:
                    # divisor가 클수록 과보정 위험이 있으므로 2분할을 우선.
                    cand_score = cand_corr
                    if 50 <= cand_speed <= 150:
                        cand_score *= 1.25
                    cand_score *= (1.0 / divisor) ** 0.15

                    item = (cand_score, cand_lag, cand_corr, cand_speed, divisor)
                    if best_short is None or item[0] > best_short[0]:
                        best_short = item

            if best_short is not None:
                _, lag, corr, implied_speed, harmonic_divisor = best_short
                harmonic_note = f"고조파보정_{harmonic_divisor}분할"

            estimated_cycles = float(total_frames) / float(lag)

            # 너무 많은 주기수는 감점
            final_score = corr
            if estimated_cycles > 100:
                final_score *= 0.45

            item = {
                "region": region,
                "period_lag_frames": float(lag),
                "period_corr": float(corr),
                "estimated_cycles": float(estimated_cycles),
                "score": float(final_score),
                "original_lag_frames": float(original_lag),
                "original_corr": float(original_corr),
                "harmonic_divisor": int(harmonic_divisor),
                "harmonic_note": harmonic_note,
                "implied_speed_kmh": float(implied_speed),
                "min_speed_kmh": float(self.min_speed_kmh),
                "max_speed_kmh": float(self.max_speed_kmh),
            }

            if best is None or item["score"] > best["score"]:
                best = item

        return best

    def run(self):
        try:
            if self.end_f <= self.start_f:
                self.failed.emit("접촉시점 프레임은 A 프레임보다 뒤여야 합니다.")
                return

            total = self.end_f - self.start_f + 1

            # 반복주기 검출을 위해 가능한 촘촘히 샘플링
            step = 1
            if total > 9000:
                step = max(1, int(total / 7000))

            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.failed.emit("영상을 다시 열 수 없습니다.")
                return

            # 중앙/좌우 차선 후보 밴드를 여러 개 동시에 평가
            # v6.7: 흐리고 짧게 끊긴 차선은 넓은 ROI에서 희석되므로 좁은 밴드도 추가한다.
            scan_regions = []
            x_bands = [
                (0.26, 0.38), (0.32, 0.46), (0.38, 0.50),
                (0.44, 0.56), (0.50, 0.62), (0.56, 0.70),
                (0.62, 0.76), (0.30, 0.72)
            ]
            y_bands = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
            for x1, x2 in x_bands:
                for y in y_bands:
                    scan_regions.append((x1, x2, y))

            # 기존 ROI 픽셀점수 + 실제 선분점수를 같이 기록한다.
            # 최종 판단은 실제 선분점수(hough_line)를 우선한다.
            scores_by_region = {r: [] for r in scan_regions}
            line_region_key = ("hough_line", "actual_lane_segments")
            scores_by_region[line_region_key] = []
            line_meta_by_frame = []
            frames = []

            sample_total = len(range(self.start_f, self.end_f + 1, step))
            last_progress = -1

            for idx, frame_idx in enumerate(range(self.start_f, self.end_f + 1, step)):
                if self._cancelled:
                    cap.release()
                    self.failed.emit("차선 자동계수가 취소됐습니다.")
                    return

                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if ret and frame is not None:
                    # 연산량 완화
                    frame = cv2.resize(frame, (640, 360))
                    mask = self.lane_mask(frame)
                    frames.append(frame_idx)

                    # 실제 차선 선분 점수
                    line_score, line_meta = self.lane_line_score(frame, mask)
                    scores_by_region[line_region_key].append(line_score)
                    line_meta_by_frame.append(line_meta)

                    # 보조 ROI 픽셀점수
                    for r in scan_regions:
                        scores_by_region[r].append(self.sample_band_score(mask, r[0], r[1], r[2]))

                if sample_total > 0:
                    pct = int((idx + 1) * 100 / sample_total)
                    if pct != last_progress and (pct % 5 == 0 or pct >= 99):
                        last_progress = pct
                        self.progress.emit(pct, f"차선 자동계수 중... {pct}%")

            cap.release()

            if len(frames) < 10:
                self.failed.emit("차선 자동계수 샘플이 부족합니다.")
                return

            candidates = []

            # 1순위: 실제 Hough 선분 기반 후보
            line_segments, line_meta = self.count_peaks_from_scores(scores_by_region[line_region_key], frames, step)
            line_raw_count = len(line_segments)
            line_scores_arr = np.array(scores_by_region[line_region_key], dtype=np.float32)
            line_nonzero_ratio = float(np.count_nonzero(line_scores_arr > 0.001)) / max(1.0, float(line_scores_arr.size))
            line_peak_strength = float(np.max(line_scores_arr)) if line_scores_arr.size else 0.0

            if line_raw_count > 0:
                line_score = line_raw_count * 3.0 + line_meta.get("std_score", 0) * 120.0 + line_peak_strength * 8.0
            else:
                line_score = -999.0
            candidates.append((line_score, line_region_key, line_segments, line_meta))

            # 2순위: 보조 ROI 픽셀점수. 단, 실제 선분이 전혀 없으면 ROI 후보는 적용하지 않는다.
            for r in scan_regions:
                segments, meta = self.count_peaks_from_scores(scores_by_region[r], frames, step)
                raw_count = len(segments)
                if raw_count == 0:
                    score = -999
                elif raw_count > 120:
                    score = 1
                else:
                    score = raw_count + meta.get("std_score", 0) * 50
                    # 실제 선분 검출이 있는 경우에만 보조 후보 인정
                    if line_nonzero_ratio <= 0.01:
                        score *= 0.05
                candidates.append((score, r, segments, meta))

            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_region, segments, meta = candidates[0]
            raw_cycle_count = len(segments)

            # 실제 선분이 거의 없으면 빈 공간/노이즈를 차선으로 보지 않고 실패 처리한다.
            if line_nonzero_ratio <= 0.01 or line_peak_strength <= 0.02:
                debug_line = f"선분검출프레임비율 {line_nonzero_ratio:.3f}, 최대선분점수 {line_peak_strength:.3f}"
                self.failed.emit(
                    "차선 자동계수 실패: 실제 차선 선분이 검출되지 않았습니다.\n\n"
                    f"{debug_line}\n\n"
                    "현재 영상 구간은 자동계수가 빈 노면/노이즈를 차선으로 오인할 가능성이 큽니다.\n"
                    "차선이 또렷하게 보이는 구간으로 시작/접촉시점을 다시 잡거나, 시작-접촉거리를 직접 입력하세요."
                )
                return

            # 자기상관도 실제 선분점수를 우선 사용한다.
            line_only_scores = {line_region_key: scores_by_region[line_region_key]}
            period_result = self.estimate_period_by_autocorr(line_only_scores, frames, step)
            if period_result is None:
                # 실제 선분 주기가 잡히지 않을 때만 전체 후보 보조 사용
                period_result = self.estimate_period_by_autocorr(scores_by_region, frames, step)

            # 기본값은 원시 피크 개수.
            cycle_count_used = float(raw_cycle_count)
            cycle_count_method = "원시감지개수"
            period_lag_frames = None
            period_corr = None
            period_region = None
            harmonic_note = ""
            harmonic_divisor = 1
            original_lag_frames = None
            original_corr = None
            implied_speed_kmh = None

            if period_result:
                period_cycles = float(period_result["estimated_cycles"])
                period_lag_frames = float(period_result["period_lag_frames"])
                period_corr = float(period_result["period_corr"])
                period_region = period_result["region"]
                harmonic_note = period_result.get("harmonic_note", "")
                harmonic_divisor = period_result.get("harmonic_divisor", 1)
                original_lag_frames = period_result.get("original_lag_frames")
                original_corr = period_result.get("original_corr")
                implied_speed_kmh = period_result.get("implied_speed_kmh")

                # 최종 후보가 최소속도보다 낮으면, 2주기를 1주기로 잘못 잡은 가능성이 높다.
                # 이 경우 lag를 절반으로 줄이면 속도는 2배가 된다.
                if implied_speed_kmh is not None and implied_speed_kmh < self.min_speed_kmh:
                    half_lag = period_lag_frames / 2.0
                    if half_lag >= 3:
                        half_speed = self.cycle_len * self.fps * 3.6 / half_lag
                        if self.min_speed_kmh <= half_speed <= self.max_speed_kmh:
                            period_lag_frames = half_lag
                            period_cycles = float(self.end_f - self.start_f) / period_lag_frames
                            implied_speed_kmh = half_speed
                            harmonic_note = "최종반토막보정_2분할"
                            harmonic_divisor = 2

                # 원시감지가 적거나, 주기추정값이 원시감지보다 명확히 크면 주기추정값을 사용.
                if raw_cycle_count < 6 or period_cycles > raw_cycle_count * 1.35:
                    cycle_count_used = period_cycles
                    cycle_count_method = "자기상관_차선주기보정"

            if cycle_count_used <= 0:
                debug = ", ".join([f"{r}:{len(segs)}" for _, r, segs, _ in candidates[:8]])
                self.failed.emit(
                    "차선표시 통과가 0개로 감지됐습니다.\n\n"
                    "실제 차선 선분을 기준으로 재검출했지만 반복 통과가 확인되지 않았습니다.\n"
                    f"스캔 결과: {debug}\n\n"
                    "이 경우 자동계수값은 적용하지 않습니다. 시작-접촉거리를 직접 입력하거나, 차선이 또렷한 구간으로 다시 잡으세요."
                )
                return

            distance_m = cycle_count_used * self.cycle_len + self.extra_m

            # v6.7: 자동계수 산출값 신뢰도 검증.
            interval_s = max(1e-6, float(self.end_f - self.start_f) / float(self.fps if self.fps else 30.0))
            auto_speed_kmh = (distance_m / interval_s) * 3.6

            hard_max_apply_speed = min(250.0, max(float(self.max_speed_kmh) * 1.25, float(self.max_speed_kmh) + 40.0))
            hard_min_apply_speed = max(3.0, float(self.min_speed_kmh) * 0.30)

            # 주기 신뢰도가 낮고 비정상 속도면 적용 차단
            confidence_bad = False
            if period_corr is not None and period_corr < 0.035:
                confidence_bad = True

            if auto_speed_kmh > hard_max_apply_speed or auto_speed_kmh < hard_min_apply_speed:
                self.failed.emit(
                    "차선 자동계수 오검출 가능성이 높아 거리값을 적용하지 않았습니다.\n\n"
                    f"자동계수 추정속도: {auto_speed_kmh:.1f}km/h\n"
                    f"허용 기준: 약 {hard_min_apply_speed:.0f}~{hard_max_apply_speed:.0f}km/h\n\n"
                    "원인: 흐리거나 끊긴 차선을 놓치고 노이즈를 차선 반복으로 잘못 잡은 경우입니다.\n"
                    "조치: 시작/접촉 구간을 차선이 더 뚜렷한 구간으로 조정하거나, 시작-접촉거리를 직접 입력하세요."
                )
                return

            if confidence_bad and raw_cycle_count < 2:
                self.failed.emit(
                    "차선 반복 신뢰도가 낮아 거리값을 적용하지 않았습니다.\n\n"
                    "흐리거나 끊긴 차선이어서 자동계수가 불안정합니다.\n"
                    "시작/접촉 구간을 조정하거나 시작-접촉거리를 직접 입력하세요."
                )
                return

            result = {
                "cycle_count": cycle_count_used,
                "raw_cycle_count": raw_cycle_count,
                "cycle_count_method": cycle_count_method,
                "median_interval_frames": period_lag_frames,
                "period_lag_frames": period_lag_frames,
                "period_corr": period_corr,
                "period_region": period_region,
                "harmonic_note": harmonic_note,
                "harmonic_divisor": harmonic_divisor,
                "original_lag_frames": original_lag_frames,
                "original_corr": original_corr,
                "implied_speed_kmh": implied_speed_kmh,
                "cycle_len_m": self.cycle_len,
                "extra_m": self.extra_m,
                "min_speed_kmh": float(self.min_speed_kmh),
                "max_speed_kmh": float(self.max_speed_kmh),
                "distance_m": distance_m,
                "auto_speed_kmh": auto_speed_kmh,
                "scan_region": best_region,
                "line_nonzero_ratio": line_nonzero_ratio,
                "line_peak_strength": line_peak_strength,
                "sample_step": int(step),
                "sample_count": int(len(frames)),
                **meta,
                "segments": [
                    {"start_frame": frames[s], "end_frame": frames[e - 1], "peak_frame": pf, "score": sc}
                    for s, e, pf, sc in segments
                ],
                "candidate_counts": {str(r): len(segs) for _, r, segs, _ in candidates[:12]},
            }

            self.progress.emit(100, "차선 자동계수 완료")
            self.finished.emit(result)

        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class BlackboxSpeedViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1560, 900)
        self.setAcceptDrops(True)

        self.cap = None
        self.video_path = None
        self.video_hash = ""
        self.output_dir = None

        self.fps = 30.0
        self.total_frames = 0
        self.width = 0
        self.height = 0
        self.current_frame_index = 0
        self.current_frame_bgr = None

        self.is_playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.play_tick)

        self.lane_count_thread = None
        self.lane_count_worker = None

        self.click_mode = None

        self.vehicle_data = {
            v: {
                "a": None,       # A: 도로 시작시점 + 차량 시작시점 + 시작 프레임
                "b_contact": None,   # B: 차량 접촉지점 + 종료 프레임
                "c_yaw": None,      # C: 피양/조향 방향점
                "yaw_start": None,  # Y: 피양 시작시점. 피양각도은 Y→C와 시작→접촉 기준축으로 계산
                "distance_ab_m": None,
                "scale_1": None, # 기준거리 시작시점
                "scale_2": None, # 기준거리 끝점
                "lane_line_1": None, # 차선 자동계수선 시작시점
                "lane_line_2": None, # 차선 자동계수선 끝점
                "lane_auto_result": None,
                "reaction_start": None,  # 제동시점/위험인지 시점
                "brake_start": None,     # 제동시점
                "impact_point": None,    # 접촉시점
                "stop_analysis": None,
                "scale_distance_m": None,
                "distance_evidence": "",
                "distance_unit_m": None,
                "distance_count": None,
            }
            for v in VEHICLES
        }

        self.speed_results = []
        self.events = []
        self.captures = []

        self.build_ui()
        self.build_menu()

    # ---------------- UI ----------------

    def make_button(self, text: str, min_width: int = 80):
        btn = QPushButton(text)
        btn.setMinimumWidth(min_width)
        btn.setMinimumHeight(28)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                font-weight: 700;
                border: 1px solid #9a9a9a;
                border-radius: 5px;
                padding: 3px 6px;
                background: #f7f7f7;
            }
            QPushButton:hover {
                background: #fff4e8;
                border: 1px solid #ff7210;
            }
            QPushButton:pressed {
                background: #ff7210;
                color: white;
                border: 2px solid #c94f00;
                padding-top: 5px;
                padding-left: 8px;
            }
            QPushButton:checked {
                background: #ff7210;
                color: white;
                border: 2px solid #c94f00;
            }
        """)
        return btn


    def make_preview_label(self, title: str) -> QLabel:
        label = QLabel(f"{title}\n미지정")
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(170, 110)
        label.setMaximumHeight(145)
        label.setStyleSheet(
            "QLabel { background-color: #222; color: #ddd; border: 1px solid #666; "
            "font-size: 12px; padding: 4px; }"
        )
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def show_license_page(self):
        """
        라이센스 모달 페이지.
        HTML이 아니라 Python 위젯(QTabWidget + QTextEdit)으로 구성한다.
        추후 라이센스 문구를 이 QTextEdit 기본값에 직접 작성하면 된다.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("라이센스")
        dialog.setModal(True)
        dialog.resize(880, 660)

        layout = QVBoxLayout(dialog)

        title = QLabel("AX4U 교통사고 영상 판독기 라이센스")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(title)

        tabs = QTabWidget(dialog)

        license_tab = QWidget()
        license_layout = QVBoxLayout(license_tab)

        license_text = QTextEdit(license_tab)
        license_text.setPlaceholderText("라이센스 내용")
        license_text.setPlainText('Made by 오정대(AX4U)\n\nAX4U 교통사고 영상 판독기 라이센스 및 사용 조건\n\n1. 저작권 및 권리 귀속\n본 프로그램의 저작권, 소스코드, UI 구성, 기능 설계, 명칭, 산출물 양식 및 관련 자료에 관한 모든 권리는 오정대(AX4U)에게 있습니다.\n본 프로그램은 AX4U 임직원 및 AX4U가 명시적으로 사용을 허락한 자를 위해 제작된 내부용 프로그램입니다.\n\n2. 사용 허가 범위\n본 프로그램은 AX4U 임직원 및 AX4U로부터 별도 사용 허가를 받은 자에 한하여 사용할 수 있습니다.\n사용 허가를 받은 경우에도 본 프로그램은 교통사고 영상 판독, 사고 분석 보조, 내부 검토 및 관련 업무 수행 목적 범위 내에서만 사용할 수 있습니다.\n\n3. 무단 사용 및 배포 금지\nAX4U 임직원 또는 AX4U의 명시적 허가를 받은 사용자가 아닌 자가 본 프로그램을 사용, 복제, 배포, 판매, 양도, 대여, 공유, 업로드, 전송 또는 제3자에게 제공하는 행위는 금지됩니다.\n무단배포 및 AX4U 임직원 외 사용 시 민·형사상 책임을 받을 수 있습니다.\n\n4. 변경, 역설계 및 파생물 제작 금지\n본 프로그램의 소스코드, 실행파일, 데이터 구조, UI, 계산 로직, 리포트 양식 등을 무단으로 수정, 변형, 역설계, 디컴파일, 분해, 재배포하거나 이를 기초로 파생 프로그램을 제작하는 행위는 금지됩니다.\n단, AX4U 또는 오정대의 명시적 허락이 있는 경우에는 예외로 합니다.\n\n5. 산출값의 성격\n본 프로그램에서 산출되는 속도, 거리, 차선계수, 피양각도, 프레임 정보, 리포트 등은 교통사고 영상 분석을 위한 보조자료입니다.\n본 프로그램의 산출값은 영상 품질, 프레임레이트, 카메라 각도, 렌즈 왜곡, 도로 구조, 차선 규격, 야간·우천·역광 여부, 차량 가림, 현장자료 유무 등에 따라 달라질 수 있습니다.\n따라서 최종 감정, 법률 판단, 보험 판단, 수사 판단 또는 법원 제출 자료로 사용할 경우에는 별도의 검토와 검증이 필요합니다.\n\n6. 책임 제한\n본 프로그램의 사용으로 인해 발생하는 직접·간접 손해, 자료 오판, 산출값 오류, 업무상 손실, 법적 분쟁, 제3자와의 분쟁 등에 대하여 AX4U 및 오정대는 고의 또는 중대한 과실이 없는 한 책임을 부담하지 않습니다.\n사용자는 본 프로그램의 산출값을 단독 근거로 확정 판단하지 않아야 하며, 필요한 경우 현장조사, 관련 법령, 전문가 검토, 공식 감정자료와 함께 종합적으로 판단해야 합니다.\n\n7. 보안 및 자료 관리\n사용자는 본 프로그램으로 처리하는 블랙박스 영상, 사고자료, 개인정보, 차량번호, 위치정보, 사건자료 등을 관련 법령과 내부 보안 기준에 따라 관리해야 합니다.\n프로그램 및 관련 자료를 외부에 제공하거나 공개할 경우 AX4U 또는 오정대의 사전 허가를 받아야 합니다.\n\n8. 라이센스 위반 시 조치\n본 라이센스 조건을 위반한 경우 AX4U 및 오정대는 프로그램 사용 중지, 자료 회수, 손해배상 청구, 형사 고소·고발 등 필요한 법적 조치를 취할 수 있습니다.\n\n9. 기타\n본 라이센스에 명시되지 않은 사항은 대한민국 법령 및 일반적인 저작권·소프트웨어 보호 원칙에 따릅니다.\n\nCopyright ⓒ 오정대(AX4U). All rights reserved.\n')
        license_text.setReadOnly(True)
        license_layout.addWidget(license_text)

        tabs.addTab(license_tab, "라이센스")
        layout.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        close_btn = QPushButton("닫기")
        close_btn.setMinimumWidth(110)
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        dialog.exec()


    def show_help_placeholder(self):
        """
        도움말 모달 페이지.
        현재는 본문을 공란으로 두고, 추후 사용법/계산식/주의사항을 넣을 수 있게 QTextBrowser만 배치한다.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("도움말")
        dialog.setModal(True)
        dialog.resize(820, 620)

        layout = QVBoxLayout(dialog)

        title = QLabel("AX4U 교통사고 영상 판독기 도움말")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(title)

        help_view = QTextBrowser(dialog)
        help_view.setOpenExternalLinks(True)
        help_view.setHtml("")
        layout.addWidget(help_view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        close_btn = QPushButton("닫기")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        dialog.exec()

    def on_road_type_changed(self, text: str):
        """
        도로구분별 차선 1주기 기본값.
        - 국도/일반도로: 차선 1개 + 차선간공간 1개 = 8m 기준
        - 도시고속화도로/자동차전용도로: 차선 1개 + 차선간공간 1개 = 20m 기준
        - 고속도로: 차선 1개 + 차선간공간 1개 = 20m 기준
        """
        if not hasattr(self, "lane_cycle_len_spin"):
            return

        if "고속도로" in text or "도시고속화도로" in text or "자동차전용도로" in text:
            self.lane_cycle_len_spin.setValue(20.0)
            if hasattr(self, "lane_auto_info"):
                self.lane_auto_info.setText(
                    f"도로구분: {text} / 차선 1주기 20m 기준. 시작/접촉 시간구간에서 차선 반복주기를 자동추정합니다."
                )
        else:
            self.lane_cycle_len_spin.setValue(8.0)
            if hasattr(self, "lane_auto_info"):
                self.lane_auto_info.setText(
                    f"도로구분: {text} / 차선 1주기 8m 기준. 시작/접촉 시간구간에서 차선 반복주기를 자동추정합니다."
                )

    def build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("파일")

        open_act = QAction("영상 열기", self)
        open_act.triggered.connect(self.open_video_dialog)
        file_menu.addAction(open_act)

        export_report_act = QAction("HTML 리포트 생성", self)
        export_report_act.triggered.connect(self.generate_html_report)
        file_menu.addAction(export_report_act)

        export_csv_act = QAction("속도 CSV 저장", self)
        export_csv_act.triggered.connect(self.export_speed_csv)
        file_menu.addAction(export_csv_act)

        file_menu.addSeparator()

        exit_act = QAction("종료", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        self.license_menu = menu.addMenu("라이센스")

        self.license_act = QAction("라이센스 확인", self)
        self.license_act.setShortcut("Ctrl+L")
        self.license_act.triggered.connect(self.show_license_page)
        self.license_menu.addAction(self.license_act)


    def build_ui(self):
        central = QWidget()
        central.setAcceptDrops(True)
        central.installEventFilter(self)
        root = QVBoxLayout(central)

        self.setStyleSheet("""
            QPushButton {
                padding: 1px 3px;
                font-size: 10px;
                min-height: 26px;
                max-height: 36px;
            }
            QLabel {
                font-size: 10px;
            }
            QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
                min-height: 24px;
                max-height: 28px;
                font-size: 10px;
            }
            QTableWidget {
                font-size: 10px;
            }
        """)

        self.video_label = VideoLabel()
        self.video_label.installEventFilter(self)
        self.video_label.image_clicked.connect(self.on_video_clicked)
        self.video_label.file_dropped.connect(self.load_video)

        self.info_label = QLabel("영상 정보: 없음")
        self.frame_label = QLabel("프레임: - / 시간: -")
        self.hash_label = QLabel("SHA-256: -")
        self.hash_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.sliderMoved.connect(self.seek_frame)

        self.btn_open = self.make_button("영상 열기", 120)
        self.btn_open.clicked.connect(self.open_video_dialog)

        self.btn_play = self.make_button("재생", 90)
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_prev10 = self.make_button("-10프레임", 100)
        self.btn_prev10.clicked.connect(lambda: self.step_frames(-10))

        self.btn_prev1 = self.make_button("-1프레임", 100)
        self.btn_prev1.clicked.connect(lambda: self.step_frames(-1))

        self.btn_next1 = self.make_button("+1프레임", 100)
        self.btn_next1.clicked.connect(lambda: self.step_frames(1))

        self.btn_next10 = self.make_button("+10프레임", 100)
        self.btn_next10.clicked.connect(lambda: self.step_frames(10))

        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(0, 0)
        self.jump_spin.setPrefix("F ")
        self.jump_spin.setMinimumWidth(110)
        self.jump_spin.setMinimumHeight(30)

        self.btn_jump = self.make_button("프레임 이동", 120)
        self.btn_jump.clicked.connect(lambda: self.seek_frame(self.jump_spin.value()))

        control_row = QHBoxLayout()
        for w in [
            self.btn_open,
            self.btn_play,
            self.btn_prev10,
            self.btn_prev1,
            self.btn_next1,
            self.btn_next10,
            self.jump_spin,
            self.btn_jump,
        ]:
            control_row.addWidget(w)

        left = QWidget()
        left.setAcceptDrops(True)
        left.installEventFilter(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.video_label, 1)
        left_layout.addWidget(self.info_label)
        left_layout.addWidget(self.frame_label)
        left_layout.addWidget(self.hash_label)
        left_layout.addWidget(self.slider)
        left_layout.addLayout(control_row)

        tabs = QTabWidget()
        tabs.setAcceptDrops(True)
        tabs.installEventFilter(self)

        speed_page = QWidget()
        speed_layout = QVBoxLayout(speed_page)
        speed_layout.setContentsMargins(8, 8, 8, 8)
        speed_layout.setSpacing(8)

        # 1행: 차량/거리/계산
        row_vehicle = QGridLayout()
        row_vehicle.setHorizontalSpacing(3)
        row_vehicle.setVerticalSpacing(3)

        self.vehicle_combo = QComboBox()
        self.vehicle_combo.addItems(VEHICLES)
        self.vehicle_combo.currentTextChanged.connect(lambda _: self.refresh_speed_status())
        self.vehicle_combo.setMinimumWidth(80)
        self.vehicle_combo.setMinimumHeight(28)

        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.0, 10000.0)
        self.distance_spin.setDecimals(1)
        self.distance_spin.setSingleStep(0.1)
        self.distance_spin.setValue(0.0)
        self.distance_spin.setSuffix(" m")
        self.distance_spin.setMinimumWidth(95)
        self.distance_spin.setMinimumHeight(28)

        self.btn_apply_distance = self.make_button("거리 적용", 95)
        self.btn_apply_distance.clicked.connect(self.apply_distance)

        # 기존 속도/피양각 계산 버튼은 판독시작 버튼으로 통합한다.
        self.btn_calc = self.make_button("판독시작", 105)
        self.btn_calc.setVisible(False)
        self.btn_calc.clicked.connect(self.start_full_analysis)

        row_vehicle.addWidget(QLabel("차량"), 0, 0)
        row_vehicle.addWidget(self.vehicle_combo, 0, 1)
        row_vehicle.addWidget(QLabel("시작-접촉 실제거리"), 0, 2)
        row_vehicle.addWidget(self.distance_spin, 0, 3)
        row_vehicle.addWidget(self.btn_apply_distance, 1, 0, 1, 4)

        # 1-2행: 차선 자동계수 전용. 수동 개수 입력 UI는 제거.
        self.distance_evidence_input = QLineEdit()
        self.distance_evidence_input.setPlaceholderText("거리 근거 메모 선택입력")
        self.distance_evidence_input.setMinimumHeight(28)

        # 1-2행: 차선표시 자동계수
        row_lane_auto = QGridLayout()
        row_lane_auto.setHorizontalSpacing(3)
        row_lane_auto.setVerticalSpacing(3)

        self.road_type_combo = QComboBox()
        self.road_type_combo.addItems([
            "국도·일반도로 기준 8m",
            "도시고속화도로·자동차전용도로 기준 20m",
            "고속도로 기준 20m",
        ])
        self.road_type_combo.setMinimumWidth(190)
        self.road_type_combo.setMinimumHeight(28)
        self.road_type_combo.currentTextChanged.connect(self.on_road_type_changed)

        self.lane_cycle_len_spin = QDoubleSpinBox()
        self.lane_cycle_len_spin.setRange(0.01, 100.0)
        self.lane_cycle_len_spin.setDecimals(1)
        self.lane_cycle_len_spin.setSingleStep(0.1)
        self.lane_cycle_len_spin.setValue(8.0)
        self.lane_cycle_len_spin.setSuffix(" m")
        self.lane_cycle_len_spin.setMinimumWidth(85)
        self.lane_cycle_len_spin.setMinimumHeight(28)
        self.lane_cycle_len_spin.valueChanged.connect(self.on_lane_distance_params_changed)

        self.lane_extra_spin = QDoubleSpinBox()
        self.lane_extra_spin.setRange(0.0, 10000.0)
        self.lane_extra_spin.setDecimals(1)
        self.lane_extra_spin.setValue(0.0)
        self.lane_extra_spin.setSuffix(" m")
        self.lane_extra_spin.setMinimumWidth(85)
        self.lane_extra_spin.setMinimumHeight(28)
        self.lane_extra_spin.valueChanged.connect(self.on_lane_distance_params_changed)

        # 자동계수 결과 저장용. 화면에는 직접 개수 입력칸으로 노출하지 않는다.
        self.lane_solid_count_spin = QDoubleSpinBox()
        self.lane_solid_count_spin.setRange(0.0, 10000.0)
        self.lane_solid_count_spin.setDecimals(1)

        self.lane_gap_count_spin = QDoubleSpinBox()
        self.lane_gap_count_spin.setRange(0.0, 10000.0)
        self.lane_gap_count_spin.setDecimals(1)

        self.btn_lane_auto = self.make_button("차선 자동계수", 105)
        self.btn_lane_auto.setObjectName("btn_lane_auto")
        self.btn_lane_auto.setMinimumHeight(28)
        self.btn_lane_auto.setMaximumHeight(34)
        self.btn_lane_auto.setStyleSheet("QPushButton { color: #ff7210; font-weight: 800; border: 1px solid #ff7210; padding: 1px 3px; } QPushButton:pressed { background:#ff7210; color:white; padding-top:4px; padding-left:6px; }")
        self.btn_lane_auto.clicked.connect(self.on_lane_auto_clicked)

        self.lane_auto_info = QLabel(
            "시작시점 = 차선계수 시작시점 / 접촉시점 = 차선계수 종료시점. "
            "흐린·끊긴 차선은 보정 인식하며, 비정상 고속 오검출은 자동 차단됩니다."
        )
        self.lane_auto_info.setWordWrap(True)

        row_lane_auto.addWidget(self.lane_auto_info, 0, 0, 1, 4)
        row_lane_auto.addWidget(QLabel("도로"), 1, 0)
        row_lane_auto.addWidget(self.road_type_combo, 1, 1, 1, 3)
        row_lane_auto.addWidget(QLabel("1주기"), 2, 0)
        row_lane_auto.addWidget(self.lane_cycle_len_spin, 2, 1)
        row_lane_auto.addWidget(QLabel("보정"), 2, 2)
        row_lane_auto.addWidget(self.lane_extra_spin, 2, 3)
        row_lane_auto.addWidget(self.btn_lane_auto, 3, 0, 1, 4)

        # 2행: 점 찍기 버튼
        row_points = QGridLayout()
        row_points.setHorizontalSpacing(3)
        row_points.setVerticalSpacing(3)

        self.btn_a = self.make_button("시작시점", 85)
        self.btn_a.clicked.connect(lambda: self.set_click_mode("a"))

        self.btn_b_contact = self.make_button("접촉시점", 90)
        self.btn_b_contact.clicked.connect(lambda: self.set_click_mode("b_contact"))

        self.btn_yaw_start = self.make_button("피양시점", 90)
        self.btn_yaw_start.clicked.connect(lambda: self.set_click_mode("yaw_start"))

        self.btn_c_road = self.make_button("피양 후 시점", 105)
        self.btn_c_road.clicked.connect(lambda: self.set_click_mode("c_yaw"))

        self.btn_copy_c_to_b = self.make_button("직선 접촉=피양후", 85)
        self.btn_copy_c_to_b.clicked.connect(self.copy_c_to_b_current_frame)

        # 시점 버튼은 지정 완료 후 눌린 상태로 고정 표시한다.
        self.point_button_map = {}

        row_points.addWidget(self.btn_a, 0, 0)
        row_points.addWidget(self.btn_b_contact, 0, 1)
        row_points.addWidget(self.btn_yaw_start, 0, 2)
        row_points.addWidget(self.btn_c_road, 1, 0)
        row_points.addWidget(self.btn_copy_c_to_b, 1, 1, 1, 2)

        # 2-1행: 정지거리 세분화 분석
        row_stop = QGridLayout()
        row_stop.setHorizontalSpacing(3)
        row_stop.setVerticalSpacing(3)

        self.btn_reaction_start = self.make_button("공주시점", 90)
        self.btn_reaction_start.clicked.connect(lambda: self.set_click_mode("reaction_start"))

        self.btn_brake_start = self.make_button("제동시점", 90)
        self.btn_brake_start.clicked.connect(lambda: self.set_click_mode("brake_start"))

        self.btn_impact_point = self.make_button("충격", 80)
        self.btn_impact_point.clicked.connect(lambda: self.set_click_mode("impact_point"))

        self.point_button_map = {
            "a": self.btn_a,
            "b_contact": self.btn_b_contact,
            "yaw_start": self.btn_yaw_start,
            "c_yaw": self.btn_c_road,
            "reaction_start": self.btn_reaction_start,
            "brake_start": self.btn_brake_start,
        }
        for _btn in self.point_button_map.values():
            _btn.setCheckable(True)
            _btn.setAutoExclusive(False)

        self.reaction_time_spin = QDoubleSpinBox()
        self.reaction_time_spin.setRange(0.1, 3.0)
        self.reaction_time_spin.setDecimals(1)
        self.reaction_time_spin.setSingleStep(0.1)
        self.reaction_time_spin.setValue(1.0)
        self.reaction_time_spin.setSuffix(" s")
        self.reaction_time_spin.setMinimumWidth(80)
        self.reaction_time_spin.setMinimumHeight(28)

        self.longitudinal_grade_spin = QDoubleSpinBox()
        self.longitudinal_grade_spin.setRange(-30.00, 30.00)
        self.longitudinal_grade_spin.setDecimals(1)
        self.longitudinal_grade_spin.setSingleStep(0.1)
        self.longitudinal_grade_spin.setValue(0.00)
        self.longitudinal_grade_spin.setSuffix(" °")
        self.longitudinal_grade_spin.setMinimumWidth(80)
        self.longitudinal_grade_spin.setMinimumHeight(28)

        self.cross_grade_spin = QDoubleSpinBox()
        self.cross_grade_spin.setRange(-30.00, 30.00)
        self.cross_grade_spin.setDecimals(1)
        self.cross_grade_spin.setSingleStep(0.1)
        self.cross_grade_spin.setValue(0.00)
        self.cross_grade_spin.setSuffix(" °")
        self.cross_grade_spin.setMinimumWidth(80)
        self.cross_grade_spin.setMinimumHeight(28)

        self.friction_mu_spin = QDoubleSpinBox()
        self.friction_mu_spin.setRange(0.01, 2.00)
        self.friction_mu_spin.setDecimals(1)
        self.friction_mu_spin.setSingleStep(0.1)
        self.friction_mu_spin.setValue(0.7)
        self.friction_mu_spin.setSuffix(" μ")
        self.friction_mu_spin.setMinimumWidth(80)
        self.friction_mu_spin.setMinimumHeight(28)

        self.vehicle_weight_spin = QDoubleSpinBox()
        self.vehicle_weight_spin.setRange(1.0, 100000.0)
        self.vehicle_weight_spin.setDecimals(1)
        self.vehicle_weight_spin.setSingleStep(0.1)
        self.vehicle_weight_spin.setValue(1500.0)
        self.vehicle_weight_spin.setSuffix(" kg")
        self.vehicle_weight_spin.setMinimumWidth(90)
        self.vehicle_weight_spin.setMinimumHeight(28)

        self.reaction_time_spin.setFixedWidth(125)
        self.friction_mu_spin.setFixedWidth(125)
        self.longitudinal_grade_spin.setFixedWidth(125)
        self.cross_grade_spin.setFixedWidth(125)
        self.vehicle_weight_spin.setFixedWidth(135)

        self.btn_stop_calc = self.make_button("판독시작", 105)
        self.btn_stop_calc.setStyleSheet("QPushButton { color: #ff7210; font-weight: 900; border: 2px solid #ff7210; padding: 1px 3px; } QPushButton:pressed { background:#ff7210; color:white; padding-top:4px; padding-left:6px; }")
        self.btn_stop_calc.clicked.connect(self.start_full_analysis)

        self.stop_result_label = QLabel("정지거리 분석: 미계산")
        self.stop_result_label.setWordWrap(True)
        self.stop_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stop_result_label.setMinimumHeight(52)
        self.stop_result_label.setMaximumHeight(90)

        def stop_param_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setStyleSheet("QLabel { font-weight: 800; }")
            label.setMinimumWidth(92)
            return label

        row_stop.setHorizontalSpacing(6)
        row_stop.setVerticalSpacing(4)
        row_stop.setColumnStretch(0, 1)
        row_stop.setColumnStretch(1, 0)
        row_stop.setColumnStretch(2, 0)
        row_stop.setColumnStretch(3, 0)
        row_stop.setColumnStretch(4, 0)
        row_stop.setColumnStretch(5, 1)

        row_stop.addWidget(self.btn_reaction_start, 0, 1)
        row_stop.addWidget(self.btn_brake_start, 0, 2)
        row_stop.addWidget(self.btn_stop_calc, 0, 3, 1, 2)

        row_stop.addWidget(stop_param_label("공주시간"), 1, 1)
        row_stop.addWidget(self.reaction_time_spin, 1, 2)
        row_stop.addWidget(stop_param_label("뮤(노면마찰계수)"), 1, 3)
        row_stop.addWidget(self.friction_mu_spin, 1, 4)

        row_stop.addWidget(stop_param_label("종단경사"), 2, 1)
        row_stop.addWidget(self.longitudinal_grade_spin, 2, 2)
        row_stop.addWidget(stop_param_label("횡단경사"), 2, 3)
        row_stop.addWidget(self.cross_grade_spin, 2, 4)

        row_stop.addWidget(stop_param_label("공차중량"), 3, 1)
        row_stop.addWidget(self.vehicle_weight_spin, 3, 2)

        row_stop.addWidget(self.stop_result_label, 4, 1, 1, 4)

        # 3행: 기타 버튼
        row_misc = QGridLayout()
        row_misc.setHorizontalSpacing(3)
        row_misc.setVerticalSpacing(3)

        self.btn_clear_vehicle = self.make_button("초기화", 80)
        self.btn_clear_vehicle.clicked.connect(self.clear_selected_vehicle)

        self.btn_export_speed = self.make_button("CSV", 70)
        self.btn_export_speed.clicked.connect(self.export_speed_csv)

        self.btn_report = self.make_button("리포트", 80)
        self.btn_report.clicked.connect(self.generate_html_report)

        row_misc.addWidget(self.btn_clear_vehicle, 0, 0)
        row_misc.addWidget(self.btn_export_speed, 0, 1)
        row_misc.addWidget(self.btn_report, 0, 2)

        self.status_label = QLabel("선택 차량: 미설정")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_label.setMinimumHeight(36)
        self.status_label.setMaximumHeight(52)

        self.preview_a = self.make_preview_label("시작시점\\n도로+차량 동시")
        self.preview_b = self.make_preview_label("접촉시점")
        self.preview_y = self.make_preview_label("피양시점")
        self.preview_c = self.make_preview_label("피양 후 시점")
        self.preview_reaction = self.make_preview_label("공주시점")
        self.preview_brake = self.make_preview_label("제동시점")
        preview_row = QGridLayout()
        preview_row.setHorizontalSpacing(3)
        preview_row.setVerticalSpacing(3)
        preview_row.addWidget(self.preview_a, 0, 0)
        preview_row.addWidget(self.preview_b, 0, 1)
        preview_row.addWidget(self.preview_y, 1, 0)
        preview_row.addWidget(self.preview_c, 1, 1)
        preview_row.addWidget(self.preview_reaction, 2, 0)
        preview_row.addWidget(self.preview_brake, 2, 1)

        self.speed_table = QTableWidget(0, 17)
        self.speed_table.setHorizontalHeaderLabels([
            "순번",
            "차량",
            "공주\n프레임",
            "제동\n프레임",
            "접촉\n프레임",
            "공주시간\n입력(s)",
            "제동\n시간(s)",
            "접촉\n시간",
            "공주시점\n속도(km/h)",
            "피양거리\n프레임비(m)",
            "횡이동\n거리(m)",
            "피양\n각도(°)",
            "공주\n거리(m)",
            "제동\n거리(m)",
            "정지\n거리(m)",
            "접촉당시\n추정속도(km/h)",
            "비고",
        ])
        self.speed_table.horizontalHeader().setStretchLastSection(False)
        self.speed_table.setWordWrap(True)
        self.speed_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.speed_table.horizontalHeader().setMinimumHeight(48)
        self.speed_table.verticalHeader().setDefaultSectionSize(46)
        self.speed_table.setMinimumHeight(135)
        self.speed_table.setColumnWidth(0, 45)
        self.speed_table.setColumnWidth(1, 60)
        self.speed_table.setColumnWidth(2, 70)
        self.speed_table.setColumnWidth(3, 70)
        self.speed_table.setColumnWidth(4, 75)
        self.speed_table.setColumnWidth(5, 75)
        self.speed_table.setColumnWidth(6, 70)
        self.speed_table.setColumnWidth(7, 90)
        self.speed_table.setColumnWidth(8, 90)
        self.speed_table.setColumnWidth(9, 95)
        self.speed_table.setColumnWidth(10, 90)
        self.speed_table.setColumnWidth(11, 95)
        self.speed_table.setColumnWidth(12, 80)
        self.speed_table.setColumnWidth(13, 80)
        self.speed_table.setColumnWidth(14, 100)
        self.speed_table.setColumnWidth(15, 105)
        self.speed_table.setColumnWidth(16, 220)
        self.speed_table.cellDoubleClicked.connect(self.on_speed_double_click)

        speed_layout.addLayout(row_vehicle)
        speed_layout.addLayout(row_lane_auto)
        speed_layout.addLayout(row_points)
        speed_layout.addLayout(row_stop)
        speed_layout.addLayout(row_misc)
        speed_layout.addWidget(self.status_label)
        speed_layout.addWidget(QLabel("지정 프레임 확인"))
        speed_layout.addLayout(preview_row)
        speed_layout.addWidget(QLabel("산출 결과"))
        speed_layout.addWidget(self.speed_table, 1)

        # 판독 탭
        analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(analysis_tab)

        event_row = QHBoxLayout()
        self.event_combo = QComboBox()
        self.event_combo.addItems(EVENT_TYPES)
        self.event_combo.setMinimumHeight(30)

        self.event_memo = QLineEdit()
        self.event_memo.setPlaceholderText("메모 예: 상대차 2차로 침범")
        self.event_memo.setMinimumHeight(30)

        self.btn_add_event = self.make_button("현재 프레임 이벤트 기록", 210)
        self.btn_add_event.clicked.connect(self.add_event)

        self.btn_capture = self.make_button("현재 프레임 캡처", 170)
        self.btn_capture.clicked.connect(self.capture_current_frame)

        event_row.addWidget(QLabel("이벤트"))
        event_row.addWidget(self.event_combo)
        event_row.addWidget(self.event_memo, 1)
        event_row.addWidget(self.btn_add_event)
        event_row.addWidget(self.btn_capture)

        self.event_table = QTableWidget(0, 5)
        self.event_table.setHorizontalHeaderLabels(["순번", "프레임", "시간", "이벤트", "메모"])
        self.event_table.horizontalHeader().setStretchLastSection(True)
        self.event_table.cellDoubleClicked.connect(self.on_event_double_click)

        self.capture_table = QTableWidget(0, 4)
        self.capture_table.setHorizontalHeaderLabels(["순번", "프레임", "시간", "파일"])
        self.capture_table.horizontalHeader().setStretchLastSection(True)

        self.report_note = QTextEdit()
        self.report_note.setPlaceholderText("판독시작을 누르면 공주거리, 제동거리, 정지거리, 공주시점~접촉시점 거리, 피양각도, 사고회피 가능성 문안이 자동 작성됩니다.")
        self.report_note.setPlaceholderText("리포트 메모")
        self.report_note.setFixedHeight(110)

        analysis_layout.addLayout(event_row)
        analysis_layout.addWidget(QLabel("이벤트 목록"))
        analysis_layout.addWidget(self.event_table, 2)
        analysis_layout.addWidget(QLabel("캡처 목록"))
        analysis_layout.addWidget(self.capture_table, 1)
        analysis_layout.addWidget(self.report_note)

        speed_scroll = QScrollArea()
        speed_scroll.setWidgetResizable(True)
        speed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        speed_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        speed_scroll.setWidget(speed_page)

        tabs.addTab(speed_scroll, "속도 산출")
        tabs.addTab(analysis_tab, "판독/리포트")

        splitter = QSplitter(Qt.Horizontal)
        splitter.setAcceptDrops(True)
        splitter.installEventFilter(self)
        splitter.addWidget(left)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter)
        self.setCentralWidget(central)

    # ---------------- Drag & Drop ----------------

    def path_from_drop_event(self, event):
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                return str(path)
        return None

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.DragEnter, QEvent.DragMove):
            path = self.path_from_drop_event(event)
            if path:
                event.acceptProposedAction()
                self.statusBar().showMessage(f"드롭 가능 영상: {Path(path).name}")
                return True
        if event.type() == QEvent.Drop:
            path = self.path_from_drop_event(event)
            if path:
                event.acceptProposedAction()
                self.load_video(path)
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        path = self.path_from_drop_event(event)
        if path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        path = self.path_from_drop_event(event)
        if path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self.path_from_drop_event(event)
        if path:
            event.acceptProposedAction()
            self.load_video(path)
        else:
            event.ignore()

    # ---------------- Video ----------------

    def open_video_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "블랙박스 영상 열기",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v);;All Files (*)",
        )
        if path:
            self.load_video(path)

    def load_video(self, path: str):
        path = str(path)
        if not Path(path).exists():
            QMessageBox.warning(self, "확인", "영상 파일을 찾을 수 없습니다.")
            return

        if self.cap:
            self.cap.release()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.critical(self, "오류", "영상을 열 수 없습니다.")
            return

        self.cap = cap
        self.video_path = path
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if self.fps <= 1 or self.fps > 240:
            self.fps = 30.0

        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.current_frame_index = 0
        self.video_label.set_source_size(self.width, self.height)

        base = safe_filename(Path(path).stem)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path(path).parent / f"{base}_판독결과_{ts}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 대용량 블랙박스 파일은 SHA-256 계산 때문에 열기 직후 멈춘 것처럼 보일 수 있어 자동 계산을 생략합니다.
        # 원본성 확인용 해시는 추후 별도 버튼으로 분리하는 편이 안전합니다.
        self.video_hash = "자동 해시 계산 생략"

        self.click_mode = None
        self.vehicle_data = {
            v: {
                "a": None,
                "b_contact": None,
                "c_yaw": None,
                "yaw_start": None,
                "distance_ab_m": None,
                "scale_1": None,
                "scale_2": None,
                "lane_line_1": None,
                "lane_line_2": None,
                "lane_auto_result": None,
                "reaction_start": None,  # 제동시점/위험인지 시점
                "brake_start": None,     # 제동시점
                "impact_point": None,    # 접촉시점
                "stop_analysis": None,
                "scale_distance_m": None,
                "distance_evidence": "",
                "distance_unit_m": None,
                "distance_count": None,
            }
            for v in VEHICLES
        }
        self.speed_results = []
        self.events = []
        self.captures = []

        self.slider.setMaximum(max(self.total_frames - 1, 0))
        self.jump_spin.setRange(0, max(self.total_frames - 1, 0))

        duration = self.total_frames / self.fps if self.fps else 0.0
        self.info_label.setText(
            f"영상 정보: {Path(path).name} | {self.width}x{self.height} | "
            f"FPS {self.fps:.1f} | 총 {self.total_frames:,} 프레임 | 길이 {seconds_to_timecode(duration)}"
        )
        self.hash_label.setText(f"SHA-256: {self.video_hash}")
        self.statusBar().showMessage(f"영상 열림: {path}")

        self.refresh_all_tables()
        self.refresh_speed_status()
        self.read_and_show_frame(0)

    def read_and_show_frame(self, frame_index: int):
        if not self.cap:
            return
        frame_index = max(0, min(int(frame_index), max(self.total_frames - 1, 0)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return
        self.current_frame_index = frame_index
        self.current_frame_bgr = frame
        self.update_frame_info()
        self.show_frame(frame)

        self.slider.blockSignals(True)
        self.slider.setValue(frame_index)
        self.slider.blockSignals(False)

        self.jump_spin.blockSignals(True)
        self.jump_spin.setValue(frame_index)
        self.jump_spin.blockSignals(False)

    def update_frame_info(self):
        sec = self.current_frame_index / self.fps if self.fps else 0.0
        self.frame_label.setText(
            f"프레임: {self.current_frame_index:,} / {max(self.total_frames - 1, 0):,} | 시간: {seconds_to_timecode(sec)}"
        )

    def draw_overlay(self, frame_bgr):
        frame = frame_bgr.copy()

        colors = {"자차": (0, 180, 255), "상대차": (0, 255, 0), "기타": (255, 0, 255)}
        names = {"자차": "EGO", "상대차": "OTHER", "기타": "ETC"}

        def draw_point(p, label, color, filled=True):
            if not p:
                return
            pt = (int(p["x"]), int(p["y"]))
            if filled:
                cv2.circle(frame, pt, 8, color, -1)
            else:
                cv2.circle(frame, pt, 8, color, 2)
            cv2.putText(frame, label, (pt[0] + 10, pt[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.68, color, 2, cv2.LINE_AA)

        selected = self.vehicle_combo.currentText() if hasattr(self, "vehicle_combo") else "자차"

        for v in VEHICLES:
            data = self.vehicle_data[v]
            color = colors[v]
            prefix = names[v]
            a = data["a"]
            b_contact = data["b_contact"]
            c_road = data["c_yaw"]
            yaw_start = data.get("yaw_start")
            scale_1 = data.get("scale_1")
            scale_2 = data.get("scale_2")
            lane_line_1 = data.get("lane_line_1")
            lane_line_2 = data.get("lane_line_2")

            if a:
                draw_point(a, f"{prefix} A F{a['frame']}", color, True)
            if b_contact:
                draw_point(b_contact, f"{prefix} B-car F{b_contact['frame']}", color, False)
            if yaw_start:
                draw_point(yaw_start, f"{prefix} Y-yaw", color, True)
            if c_road:
                draw_point(c_road, f"{prefix} C-yaw", color, False)
            if scale_1:
                draw_point(scale_1, f"{prefix} REF1", (255, 255, 0), True)
            if scale_2:
                draw_point(scale_2, f"{prefix} REF2", (255, 255, 0), False)
            if scale_1 and scale_2:
                cv2.line(frame, (scale_1["x"], scale_1["y"]), (scale_2["x"], scale_2["y"]), (255, 255, 0), 2)

            if lane_line_1:
                draw_point(lane_line_1, f"{prefix} L1", (0, 255, 255), True)
            if lane_line_2:
                draw_point(lane_line_2, f"{prefix} L2", (0, 255, 255), False)
            if lane_line_1 and lane_line_2:
                cv2.line(frame, (lane_line_1["x"], lane_line_1["y"]), (lane_line_2["x"], lane_line_2["y"]), (0, 255, 255), 2)

            if a and c_road:
                cv2.line(frame, (a["x"], a["y"]), (c_road["x"], c_road["y"]), color, 2 if v == selected else 1)
                if data["distance_ab_m"] is not None:
                    mid = ((a["x"] + c_road["x"]) // 2, (a["y"] + c_road["y"]) // 2)
                    cv2.putText(frame, f"{v} 시작-접촉 {data['distance_ab_m']:.1f}m", (mid[0] + 8, mid[1] + 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

            if a and b_contact:
                cv2.line(frame, (a["x"], a["y"]), (b_contact["x"], b_contact["y"]), color, 1)

            if yaw_start and c_road:
                cv2.line(frame, (yaw_start["x"], yaw_start["y"]), (c_road["x"], c_road["y"]), color, 2 if v == selected else 1)
            elif b_contact and c_road:
                cv2.line(frame, (b_contact["x"], b_contact["y"]), (c_road["x"], c_road["y"]), color, 1)

        if self.click_mode:
            txt = {
                "a": "CLICK: A start",
                "b_contact": "CLICK: B vehicle end",
                "c_yaw": "CLICK: C road end",
                "scale_1": "CLICK: reference start",
                "scale_2": "CLICK: reference end",
                "lane_line_1": "CLICK: lane count line 1",
                "lane_line_2": "CLICK: lane count line 2",
            }.get(self.click_mode, f"CLICK: {self.click_mode}")
            cv2.rectangle(frame, (10, 10), (560, 52), (0, 0, 0), -1)
            cv2.putText(frame, txt, (22, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        return frame

    def show_frame(self, frame_bgr):
        if frame_bgr is None:
            return
        frame = self.draw_overlay(frame_bgr)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        self.video_label.setPixmap(
            pix.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)
        if hasattr(self, "preview_a"):
            self.refresh_previews()

    def seek_frame(self, value: int):
        self.pause()
        self.read_and_show_frame(value)

    def step_frames(self, delta: int):
        self.pause()
        self.read_and_show_frame(self.current_frame_index + delta)

    def toggle_play(self):
        if not self.cap:
            return
        if self.is_playing:
            self.pause()
            return
        self.is_playing = True
        self.btn_play.setText("일시정지")
        self.timer.start(max(1, int(1000 / self.fps)))

    def pause(self):
        self.is_playing = False
        self.btn_play.setText("재생")
        self.timer.stop()

    def play_tick(self):
        if not self.cap:
            self.pause()
            return
        nxt = self.current_frame_index + 1
        if nxt >= self.total_frames:
            self.pause()
            return
        self.read_and_show_frame(nxt)

    # ---------------- Speed ----------------

    def update_point_button_states(self):
        """
        각 시점이 지정되면 해당 버튼을 눌린 상태로 고정 표시한다.
        """
        if not hasattr(self, "point_button_map"):
            return
        try:
            data = self.selected_vehicle_data()
        except Exception:
            return

        for key, btn in self.point_button_map.items():
            try:
                btn.blockSignals(True)
                btn.setChecked(bool(data.get(key)))
            finally:
                btn.blockSignals(False)

    def mark_point_saved(self):
        self.update_point_button_states()

    def selected_vehicle_data(self):
        return self.vehicle_data[self.vehicle_combo.currentText()]

    def set_click_mode(self, mode: str):
        if not self.video_path:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return
        self.pause()
        self.click_mode = mode
        v = self.vehicle_combo.currentText()
        msg = {
            "a": f"{v}: 시작시점입니다. 차량이 시작시점에 있는 프레임에서 차량 기준점을 클릭하세요.",
            "b_contact": f"{v}: 접촉시점입니다. 차량이 접촉지점에 있는 프레임에서 클릭하세요.",
            "yaw_start": f"{v}: 피양시점입니다. 피양이 시작되는 위치/방향 기준점을 클릭하세요.",
            "c_yaw": f"{v}: 피양 후 시점입니다. 피양 후 횡이동한 방향/끝점을 클릭하세요.",
            "scale_1": f"{v}: 기준거리 시작시점 클릭 기능은 비권장입니다. 실제거리 근거입력을 사용하세요.",
            "scale_2": f"{v}: 기준거리 끝점 클릭 기능은 비권장입니다. 실제거리 근거입력을 사용하세요.",
            "lane_line_1": f"{v}: 이 기능은 시작시점 버튼으로 통합됐습니다.",
            "lane_line_2": f"{v}: 이 기능은 접촉시점 버튼으로 통합됐습니다.",
            "reaction_start": f"{v}: 공주시점입니다. 운전자가 위험을 인지한 프레임에서 차량 기준점을 클릭하세요.",
            "brake_start": f"{v}: 제동시점입니다. 실제 감속/제동이 시작된 프레임에서 차량 기준점을 클릭하세요.",
        }.get(mode, "영상 위 점을 클릭하세요.")
        self.statusBar().showMessage(msg + " | 공주시점속도=공주거리÷공주시간")
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)

    def on_video_clicked(self, x: int, y: int):
        if not self.click_mode:
            self.statusBar().showMessage(f"클릭 좌표: ({x}, {y})")
            return

        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        if self.click_mode == "a":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["a"] = p
            # 시작시점은 차량 시작시점이자 차선계수 시작시점이다.
            data["lane_line_1"] = make_position_only(self.current_frame_index, self.fps, x, y)
            self.statusBar().showMessage(f"{v} 시작시점 저장: F{p['frame']} {p['timecode']} ({x}, {y}) / 차선계수 시작시점도 동시 저장")
        elif self.click_mode == "b_contact":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["b_contact"] = p
            # 접촉시점 = 접촉시점. 별도 접촉시점 버튼 없이 접촉시점을 접촉시점으로 자동 사용한다.
            data["impact_point"] = dict(p)
            # 접촉시점은 차량 접촉지점이자 차선계수 종료시점이다.
            data["lane_line_2"] = make_position_only(self.current_frame_index, self.fps, x, y)
            self.statusBar().showMessage(f"{v} 접촉시점 저장: F{p['frame']} {p['timecode']} ({x}, {y}) / 접촉시점도 동시 저장")
        elif self.click_mode == "yaw_start":
            p = make_position_only(self.current_frame_index, self.fps, x, y)
            data["yaw_start"] = p
            self.statusBar().showMessage(f"{v} 피양시점 저장: ({x}, {y})")
        elif self.click_mode == "c_yaw":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["c_yaw"] = p
            self.statusBar().showMessage(f"{v} 피양 후 시점 저장: F{p['frame']} {p['timecode']} ({x}, {y})")
        elif self.click_mode == "reaction_start":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["reaction_start"] = p
            self.statusBar().showMessage(f"{v} 공주시점 저장: F{p['frame']} {p['timecode']} ({x}, {y})")
        elif self.click_mode == "brake_start":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["brake_start"] = p
            self.statusBar().showMessage(f"{v} 제동시점 저장: F{p['frame']} {p['timecode']} ({x}, {y})")
        elif self.click_mode == "impact_point":
            p = make_frame_point(self.current_frame_index, self.fps, x, y)
            data["impact_point"] = p
            self.statusBar().showMessage(f"{v} 접촉시점 저장: F{p['frame']} {p['timecode']} ({x}, {y})")
        elif self.click_mode == "scale_1":
            p = make_position_only(self.current_frame_index, self.fps, x, y)
            data["scale_1"] = p
            self.statusBar().showMessage(f"{v} 기준거리 시작시점 저장: ({x}, {y})")
        elif self.click_mode == "scale_2":
            p = make_position_only(self.current_frame_index, self.fps, x, y)
            data["scale_2"] = p
            self.statusBar().showMessage(f"{v} 기준거리 끝점 저장: ({x}, {y})")
        elif self.click_mode == "lane_line_1":
            p = make_position_only(self.current_frame_index, self.fps, x, y)
            data["lane_line_1"] = p
            self.statusBar().showMessage(f"{v} 차선 계수선 시작시점 저장: ({x}, {y})")
        elif self.click_mode == "lane_line_2":
            p = make_position_only(self.current_frame_index, self.fps, x, y)
            data["lane_line_2"] = p
            self.statusBar().showMessage(f"{v} 차선 계수선 끝점 저장: ({x}, {y})")

        self.click_mode = None
        self.refresh_speed_status()
        self.update_point_button_states()
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)

    def on_lane_auto_clicked(self):
        """차선 자동계수 버튼 클릭 전용 래퍼."""
        self.statusBar().showMessage("차선 자동계수 버튼 클릭됨")
        if hasattr(self, "lane_auto_info"):
            self.lane_auto_info.setText("차선 자동계수 준비 중...")
        QTimer.singleShot(80, self.auto_count_lane_marks)

    def sample_lane_line_score(self, frame, p1, p2, thickness=9):
        """
        사용자가 지정한 계수선 위를 지나가는 흰색/밝은 차선표시의 비율을 점수화한다.
        """
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.line(mask, (int(p1["x"]), int(p1["y"])), (int(p2["x"]), int(p2["y"])), 255, int(thickness))

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 흰색 차선 + 밝은 회색 차선을 같이 잡는다.
        white = (((v > 155) & (s < 115)) | (gray > 195)).astype(np.uint8)

        selected = white[mask > 0]
        if selected.size == 0:
            return 0.0
        return float(selected.mean())

    def auto_count_lane_marks(self):
        """
        차선 자동계수를 백그라운드 스레드에서 실행한다.
        메인 UI 스레드에서 프레임을 읽으면 버튼 눌림 모션도 보이지 않고 창이 멈추므로 반드시 분리한다.
        """
        if self.lane_count_thread is not None:
            QMessageBox.information(self, "진행 중", "차선 자동계수가 이미 실행 중입니다.")
            return

        if not self.video_path:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return

        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        required = ["a", "b_contact"]
        missing = [key for key in required if not data.get(key)]
        if missing:
            QMessageBox.warning(
                self,
                "확인",
                "차선 자동계수를 위해 먼저 시작시점과 접촉시점을 찍어야 합니다.\n"
                "시작시점은 차선계수 시작시점, 접촉시점은 차선계수 종료시점으로 자동 사용됩니다."
            )
            return

        # 시작/접촉를 차선계수 시작/종료점으로 강제 동기화한다.
        data["lane_line_1"] = make_position_only(data["a"]["frame"], self.fps, data["a"]["x"], data["a"]["y"])
        data["lane_line_2"] = make_position_only(data["b_contact"]["frame"], self.fps, data["b_contact"]["x"], data["b_contact"]["y"])

        start_f = self.get_point_frame(data, "a")
        end_f = self.get_point_frame(data, "b_contact")
        if end_f <= start_f:
            QMessageBox.warning(self, "확인", "접촉시점 프레임은 A 프레임보다 뒤여야 합니다.")
            return

        cycle_len = float(self.lane_cycle_len_spin.value()) if hasattr(self, "lane_cycle_len_spin") else 8.0
        extra_m = float(self.lane_extra_spin.value()) if hasattr(self, "lane_extra_spin") else 0.0
        # 화면의 속도범위 입력은 삭제했다. 자동계수 내부 오검출 방지용 기본값만 사용한다.
        min_speed_kmh = 60.0
        max_speed_kmh = 160.0

        self.btn_lane_auto.setEnabled(False)
        self.btn_lane_auto.setText("자동계수 실행 중...")
        if hasattr(self, "lane_auto_info"):
            self.lane_auto_info.setText("차선 자동계수 시작... 창은 멈추지 않습니다.")
        self.statusBar().showMessage("차선 자동계수 시작")

        self.lane_count_thread = QThread(self)
        self.lane_count_worker = LaneCountWorker(
            self.video_path,
            start_f,
            end_f,
            self.fps,
            data["lane_line_1"],
            data["lane_line_2"],
            cycle_len,
            extra_m,
            min_speed_kmh,
            max_speed_kmh,
        )
        self.lane_count_worker.moveToThread(self.lane_count_thread)

        self.lane_count_thread.started.connect(self.lane_count_worker.run)
        self.lane_count_worker.progress.connect(self.on_lane_count_progress)
        self.lane_count_worker.finished.connect(self.on_lane_count_finished)
        self.lane_count_worker.failed.connect(self.on_lane_count_failed)

        self.lane_count_worker.finished.connect(self.lane_count_thread.quit)
        self.lane_count_worker.failed.connect(self.lane_count_thread.quit)
        self.lane_count_thread.finished.connect(self.lane_count_worker.deleteLater)
        self.lane_count_thread.finished.connect(self.lane_count_thread.deleteLater)
        self.lane_count_thread.finished.connect(self.cleanup_lane_count_thread)

        self.lane_count_thread.start()

    def on_lane_count_progress(self, pct: int, msg: str):
        self.statusBar().showMessage(msg)
        if hasattr(self, "lane_auto_info"):
            self.lane_auto_info.setText(msg)

    def on_lane_count_finished(self, result: dict):
        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        cycle_count = float(result["cycle_count"])
        raw_cycle_count = int(result.get("raw_cycle_count", round(cycle_count)))
        cycle_method = result.get("cycle_count_method", "원시감지개수")
        period_lag = result.get("period_lag_frames")
        period_corr = result.get("period_corr")
        harmonic_note = result.get("harmonic_note", "")
        harmonic_divisor = result.get("harmonic_divisor", 1)
        original_lag = result.get("original_lag_frames")
        original_corr = result.get("original_corr")
        implied_speed = result.get("implied_speed_kmh")
        auto_speed = result.get("auto_speed_kmh")
        min_speed = result.get("min_speed_kmh")
        max_speed = result.get("max_speed_kmh")
        cycle_len = float(result["cycle_len_m"])
        extra_m = float(result["extra_m"])
        distance_m = float(result["distance_m"])

        self.lane_solid_count_spin.setValue(float(cycle_count))
        self.lane_gap_count_spin.setValue(float(cycle_count))
        self.distance_spin.setValue(distance_m)

        data["distance_ab_m"] = distance_m
        self.clear_speed_results_for_vehicle(v)
        road_type = self.road_type_combo.currentText() if hasattr(self, "road_type_combo") else ""
        data["distance_evidence"] = (
            f"차선 자동계수: 도로구분 {road_type}, 원시감지 {raw_cycle_count}회, 적용주기 {cycle_count:.1f}회, "
            f"방식 {cycle_method}, 1주기 {cycle_len:.1f}m + 부분보정 {extra_m:.1f}m"
        )
        result["road_type"] = road_type
        data["lane_auto_result"] = result

        if hasattr(self, "lane_auto_info"):
            extra_txt = ""
            if period_lag:
                extra_txt = f" / 적용주기 {period_lag:.1f}F"
            if harmonic_note:
                extra_txt += f" / {harmonic_note}"
            self.lane_auto_info.setText(
                f"차선 자동계수값: 원시 {raw_cycle_count}회 → 적용 {cycle_count:.1f}주기 × {cycle_len:.1f}m "
                f"+ 부분 {extra_m:.1f}m = 시작-접촉 {distance_m:.1f}m / {cycle_method}{extra_txt}"
                + (f" / 산출속도 {auto_speed:.1f}km/h" if auto_speed else "")
            )

        self.refresh_speed_status()
        self.update_point_button_states()
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)

        detail = (
            f"도로구분: {road_type}\n"
            f"영상 원시감지: 차선표시 {raw_cycle_count}회\n"
            f"거리계산 적용주기: {cycle_count:.1f}회\n"
            f"보정방식: {cycle_method}\n"
        )
        if original_lag:
            detail += f"최초 선택주기: {original_lag:.1f}프레임\n"
        if period_lag:
            detail += f"적용 추정주기: {period_lag:.1f}프레임\n"
        if harmonic_note:
            detail += f"반토막 보정: {harmonic_note}\n"
        if period_corr is not None:
            detail += f"주기 신뢰도: {period_corr:.1f}\n"
        if implied_speed:
            detail += f"주기상 암시속도: {implied_speed:.1f}km/h\n"
        if auto_speed:
            detail += f"자동계수 산출속도: {auto_speed:.1f}km/h\n"
        if result.get("line_nonzero_ratio") is not None:
            detail += f"차선선분 검출비율: {result.get('line_nonzero_ratio'):.3f}\n"
        if result.get("line_peak_strength") is not None:
            detail += f"차선선분 최대점수: {result.get('line_peak_strength'):.3f}\n"
        if min_speed is not None and max_speed is not None:
            detail += f"적용 속도범위: {min_speed:.0f}~{max_speed:.0f}km/h\n"

        QMessageBox.information(
            self,
            "차선 자동계수 완료",
            detail
            + "\n"
            + f"시작-접촉거리 = {distance_m:.1f}m\n"
            + (f"자동계수 산출속도 = {auto_speed:.1f}km/h\n" if auto_speed else "")
            + f"계산식 = 적용주기 {cycle_count:.1f}회 × 1주기 {cycle_len:.1f}m + 부분 {extra_m:.1f}m\n\n"
            + "기준: 차선 1개 + 차선간공간 1개 = 8m\n"
            + "오검출이 있으면 시작/접촉 시간구간을 조정하거나 차선이 잘 보이는 구간을 사용하세요."
        )

    def on_lane_count_failed(self, message: str):
        if hasattr(self, "lane_auto_info"):
            self.lane_auto_info.setText(f"차선 자동계수 실패: {message}")
        QMessageBox.warning(self, "차선 자동계수 실패", message)

    def cleanup_lane_count_thread(self):
        self.lane_count_thread = None
        self.lane_count_worker = None
        if hasattr(self, "btn_lane_auto"):
            self.btn_lane_auto.setEnabled(True)
            self.btn_lane_auto.setText("차선 자동계수 실행\n시작-접촉 거리 자동입력")
        self.statusBar().showMessage("차선 자동계수 대기")


    def estimate_ab_distance_from_scale(self):
        """
        자차 블랙박스 장거리 이동에서는 픽셀거리 기반 시작-접촉거리 추정 금지.
        카메라가 이동하고 원근이 변하므로 시작프레임 A와 종료프레임 B의 픽셀차는 실제 주행거리와 대응하지 않는다.
        """
        self.show_pixel_distance_warning()

    def show_pixel_distance_warning(self):
        QMessageBox.warning(
            self,
            "픽셀거리 추정 금지",
            "자차 블랙박스에서는 카메라가 차량과 함께 이동합니다.\n\n"
            "따라서 사고 이전 A점부터 접촉점 B까지 250m를 주행했더라도,\\n"
            "영상 화면 안에서 A와 B의 픽셀차는 21m처럼 잘못 환산될 수 있습니다.\n\n"
            "시작-접촉거리는 아래 근거로 입력해야 합니다. 차선표시는 프로그램이 자동계수할 수 있습니다.\\n"
            "- 지도/로드뷰 거리\\n"
            "- 현장 실측거리\\n"
            "- 차선표시, 정지선, 횡단보도, 가로등/가로수 간격\\n"
            "- 주정차 차량 길이 또는 도로시설물 간격\\n"
            "- 차량 차량자료\n\n"
            "영상은 거리 산정이 아니라 시작/접촉 프레임 시간차와 피양각도 판독에 사용합니다."
        )

    def apply_distance_from_evidence(self):
        QMessageBox.warning(
            self,
            "사용 안 함",
            "단위거리×개수 수동 입력 기능은 UI에서 제거했습니다.\n"
            "차선 자동계수 버튼을 사용하거나, 상단 시작-접촉거리 수동입력 버튼을 사용하세요."
        )

    def clear_speed_results_for_vehicle(self, vehicle_name=None):
        """
        같은 차량의 예전 판독행이 남아 예전 속도값처럼 보이는 문제를 막는다.
        """
        try:
            if vehicle_name is None:
                vehicle_name = self.vehicle_combo.currentText()
            self.speed_results = [r for r in self.speed_results if r.get("vehicle") != vehicle_name]
            self.refresh_speed_table()
        except Exception:
            pass

    def sync_distance_from_ui(self, clear_previous: bool = False):
        """
        현재 화면의 시작-접촉 실제거리 입력값을 계산용 data에 강제 동기화한다.
        판독시작 직전에 반드시 호출한다.
        """
        data = self.selected_vehicle_data()
        distance_m = float(self.distance_spin.value()) if hasattr(self, "distance_spin") else 0.0

        if distance_m <= 0.0:
            data["distance_ab_m"] = None
            return None

        old_distance = data.get("distance_ab_m")
        data["distance_ab_m"] = distance_m
        if not data.get("distance_evidence"):
            data["distance_evidence"] = "화면 입력 거리"

        if clear_previous and old_distance is not None:
            try:
                if abs(float(old_distance) - float(distance_m)) > 1e-6:
                    self.clear_speed_results_for_vehicle()
            except Exception:
                self.clear_speed_results_for_vehicle()

        return distance_m

    def on_lane_distance_params_changed(self, *args):
        """
        차선 자동계수 후 1주기/보정값을 바꾸면 시작-접촉거리도 즉시 다시 계산한다.
        """
        try:
            count = float(self.lane_solid_count_spin.value()) if hasattr(self, "lane_solid_count_spin") else 0.0
            cycle_len = float(self.lane_cycle_len_spin.value()) if hasattr(self, "lane_cycle_len_spin") else 0.0
            extra = float(self.lane_extra_spin.value()) if hasattr(self, "lane_extra_spin") else 0.0

            if count <= 0 or cycle_len <= 0:
                return

            new_distance = count * cycle_len + extra
            if new_distance <= 0:
                return

            if hasattr(self, "distance_spin"):
                self.distance_spin.blockSignals(True)
                self.distance_spin.setValue(float(new_distance))
                self.distance_spin.blockSignals(False)

            data = self.selected_vehicle_data()
            old_distance = data.get("distance_ab_m")
            data["distance_ab_m"] = float(new_distance)
            data["distance_evidence"] = f"차선 자동계수 보정반영: {count:.1f}주기 × {cycle_len:.1f}m + {extra:.1f}m"

            if old_distance is not None:
                try:
                    if abs(float(old_distance) - float(new_distance)) > 1e-6:
                        self.clear_speed_results_for_vehicle()
                except Exception:
                    self.clear_speed_results_for_vehicle()

            if hasattr(self, "lane_auto_info"):
                self.lane_auto_info.setText(
                    f"차선거리 보정 적용: {count:.1f}주기 × {cycle_len:.1f}m + {extra:.1f}m = {new_distance:.1f}m"
                )

            self.refresh_speed_status()
        except Exception:
            pass

    def apply_distance(self):
        data = self.selected_vehicle_data()
        distance_m = float(self.distance_spin.value())

        if distance_m <= 0.0:
            data["distance_ab_m"] = None
            self.refresh_speed_status()
            self.statusBar().showMessage("거리 적용 실패: 시작-접촉 실제거리를 입력해야 합니다.")
            QMessageBox.warning(
                self,
                "거리 입력 필요",
                "시작-접촉 실제거리를 먼저 입력하세요.\n\n"
                "0.0 m는 계산에 적용할 수 없습니다."
            )
            return

        data["distance_ab_m"] = distance_m
        self.clear_speed_results_for_vehicle()
        data["distance_evidence"] = (
            self.distance_evidence_input.text().strip()
            if hasattr(self, "distance_evidence_input")
            else "수동입력 거리"
        ) or "수동입력 거리"

        self.refresh_speed_status()
        self.statusBar().showMessage(f"거리 적용 완료: 시작-접촉거리 {distance_m:.1f} m")

        QMessageBox.information(
            self,
            "거리 적용",
            f"거리 적용 완료\n\n시작-접촉거리: {distance_m:.1f} m"
        )

        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)


    def copy_c_to_b_current_frame(self):
        """직선구간용: 접촉시점 좌표는 피양 후방향점과 같게 하되, 프레임은 현재 프레임으로 저장."""
        if not self.video_path:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return

        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        if not data["c_yaw"]:
            QMessageBox.warning(self, "확인", "먼저 피양 후 시점을 찍어야 합니다.")
            return

        c = data["c_yaw"]
        data["b_contact"] = make_frame_point(self.current_frame_index, self.fps, c["x"], c["y"])
        self.refresh_speed_status()
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)
        self.statusBar().showMessage(
            f"{v} 접촉시점 저장: 좌표=피양 후({c['x']},{c['y']}), 프레임=현재 F{data['b_contact']['frame']} {data['b_contact']['timecode']}"
        )

    def clear_selected_vehicle(self):
        v = self.vehicle_combo.currentText()
        self.vehicle_data[v] = {
            "a": None,
            "b_contact": None,
            "c_yaw": None,
            "yaw_start": None,
            "distance_ab_m": None,
            "scale_1": None,
            "scale_2": None,
            "lane_line_1": None,
            "lane_line_2": None,
            "lane_auto_result": None,
            "reaction_start": None,
            "brake_start": None,
            "impact_point": None,
            "stop_analysis": None,
            "scale_distance_m": None,
            "distance_evidence": "",
            "distance_unit_m": None,
            "distance_count": None,
        }
        if hasattr(self, "lane_auto_info"):
            self.lane_auto_info.setText("시작시점/접촉시점은 시간구간입니다. 도로구분에 따라 차선 1주기를 국도·일반도로 8m, 도시고속화도로·자동차전용도로 20m, 고속도로 20m로 설정해 자동환산합니다.")
        if hasattr(self, "stop_result_label"):
            self.stop_result_label.setText("정지거리 분석: 미계산")
        self.refresh_speed_status()
        if self.current_frame_bgr is not None:
            self.show_frame(self.current_frame_bgr)

    def calculate_lateral_geometry(self, a, b_contact, yaw_start, c_yaw, distance_ab_m):
        """
        A→접촉시점을 기준 진행방향으로 보고, 피양시점→피양 후방향이
        진행방향에서 몇 도 꺾였는지를 계산한다.

        기존처럼 signed angle을 그대로 표시하면 -각도가 나와 혼란스럽다.
        감정 실무상 필요한 값은 '진행방향 대비 꺾인 절대각'이므로:
            예) 진행방향 180°, 피양 후 175° → 피양각도 5°
        로 표시한다.

        signed 값은 내부 기록용으로 보존하고, 화면/표에는 절대 꺾임각을 표시한다.
        """
        ax, ay = float(a["x"]), float(a["y"])
        bx, by = float(b_contact["x"]), float(b_contact["y"])
        yx, yy = float(yaw_start["x"]), float(yaw_start["y"])
        cx, cy = float(c_yaw["x"]), float(c_yaw["y"])

        base_dx, base_dy = bx - ax, by - ay
        yaw_dx, yaw_dy = cx - yx, cy - yy

        base_px = math.hypot(base_dx, base_dy)
        yaw_px = math.hypot(yaw_dx, yaw_dy)

        if base_px <= 0:
            raise ValueError("A-접촉시점 기준선의 화면상 거리가 0입니다.")
        if yaw_px <= 0:
            raise ValueError("Y-피양 후 시점 후선의 화면상 거리가 0입니다. Y와 C를 서로 다른 지점으로 찍어야 합니다.")

        # 시작→접촉 기준 단위벡터
        ux, uy = base_dx / base_px, base_dy / base_px

        # Y→피양 후 시점벡터의 시작→접촉 기준축 성분
        yaw_longitudinal_px = yaw_dx * ux + yaw_dy * uy
        yaw_lateral_px = yaw_dx * uy - yaw_dy * ux

        # signed angle: -180~180도
        signed_angle_deg = math.degrees(math.atan2(yaw_lateral_px, yaw_longitudinal_px))

        # 화면 표시는 '몇 도 꺾였는지'이므로 절대각
        bend_angle_deg = abs(signed_angle_deg)

        # atan2 결과는 이미 -180~180이지만, 혹시 모를 정규화
        if bend_angle_deg > 180.0:
            bend_angle_deg = 360.0 - bend_angle_deg

        meters_per_px = distance_ab_m / base_px
        yaw_longitudinal_m = yaw_longitudinal_px * meters_per_px
        yaw_lateral_m = yaw_lateral_px * meters_per_px
        yaw_lateral_abs_m = abs(yaw_lateral_m)
        yaw_vector_distance_m = math.hypot(yaw_longitudinal_m, yaw_lateral_m)

        # 좌/우 방향은 참고값. 이미지 좌표계라 실제 좌우와 100% 일치하지 않을 수 있어 보조값으로만 기록.
        if signed_angle_deg > 0:
            yaw_direction = "우측/시계방향"
        elif signed_angle_deg < 0:
            yaw_direction = "좌측/반시계방향"
        else:
            yaw_direction = "직진"

        frame_gap = None
        if "marked_frame" in yaw_start and "marked_frame" in c_yaw:
            frame_gap = abs(int(c_yaw["marked_frame"]) - int(yaw_start["marked_frame"]))

        return {
            "base_px": base_px,
            "yaw_px": yaw_px,
            "meters_per_px": meters_per_px,
            "yaw_longitudinal_m": yaw_longitudinal_m,
            "yaw_lateral_m": yaw_lateral_m,
            "yaw_lateral_abs_m": yaw_lateral_abs_m,
            "yaw_vector_distance_m": yaw_vector_distance_m,
            "yaw_angle_signed_deg": signed_angle_deg,
            "yaw_angle_deg": bend_angle_deg,
            "yaw_direction": yaw_direction,
            "yaw_frame_gap": frame_gap,
        }

    def current_ab_speed_kmh(self, data):
        if not data.get("a") or not data.get("b_contact") or data.get("distance_ab_m") is None:
            return None
        frame_delta = self.get_point_frame(data, "b_contact") - self.get_point_frame(data, "a")
        if frame_delta <= 0 or not self.fps:
            return None
        time_s = frame_delta / self.fps
        if time_s <= 0:
            return None
        return (float(data["distance_ab_m"]) / time_s) * 3.6

    def estimate_interval_distance_by_ab_projection(self, data, start_key: str, end_key: str):
        """
        시작시점→접촉시점 화면 기준선을 실제 시작-접촉거리(m)의 축으로 보고,
        임의 구간(start_key→end_key)의 진행방향 투영거리를 m 단위로 추정한다.

        이 함수는 프레임비가 아니라 '찍은 좌표'를 보므로,
        제동시점을 다르게 찍으면 공주시점 속도와 제동거리가 달라진다.
        """
        if not data.get(start_key) or not data.get(end_key):
            return None
        if not data.get("a") or not data.get("b_contact") or data.get("distance_ab_m") is None:
            return None

        a = data["a"]
        b = data["b_contact"]
        s = data[start_key]
        e = data[end_key]

        ax, ay = float(a["x"]), float(a["y"])
        bx, by = float(b["x"]), float(b["y"])
        sx, sy = float(s["x"]), float(s["y"])
        ex, ey = float(e["x"]), float(e["y"])

        base_dx = bx - ax
        base_dy = by - ay
        base_px = math.hypot(base_dx, base_dy)
        if base_px <= 0:
            return None

        ux = base_dx / base_px
        uy = base_dy / base_px

        section_dx = ex - sx
        section_dy = ey - sy

        # 진행방향 성분만 거리로 사용
        projected_px = section_dx * ux + section_dy * uy
        meters_per_px = float(data["distance_ab_m"]) / base_px

        distance_m = projected_px * meters_per_px

        # 역방향 클릭값은 계산 오류로 보고 0으로 클램프
        if distance_m < 0:
            distance_m = 0.0

        return distance_m

    def get_point_frame(self, data, key: str):
        """
        시점 dict에서 frame 값을 안전하게 꺼낸다.
        frame 키가 없으면 None.
        """
        try:
            p = data.get(key)
            if not isinstance(p, dict):
                return None
            if "frame" not in p:
                return None
            return int(p.get("frame"))
        except Exception:
            return None

    def get_point_timecode(self, data, key: str):
        try:
            p = data.get(key)
            if not isinstance(p, dict):
                return ""
            return str(p.get("timecode", ""))
        except Exception:
            return ""

    def validate_required_points_have_frames(self, data, keys):
        missing = []
        label_map = {
            "a": "시작시점",
            "reaction_start": "공주시점",
            "brake_start": "제동시점",
            "b_contact": "접촉시점",
            "yaw_start": "피양시점",
            "c_yaw": "피양 후 시점",
        }
        for key in keys:
            if not isinstance(data.get(key), dict):
                missing.append(label_map.get(key, key))
            elif self.get_point_frame(data, key) is None:
                missing.append(label_map.get(key, key) + " 프레임값")
        return missing

    def section_frame_delta(self, data, start_key: str, end_key: str):
        sf = self.get_point_frame(data, start_key)
        ef = self.get_point_frame(data, end_key)
        if sf is None or ef is None:
            return None
        return ef - sf

        if not data.get(start_key) or not data.get(end_key):
            return None
        return int(data[end_key]["frame"]) - int(data[start_key]["frame"])

    def section_time_s(self, data, start_key: str, end_key: str):
        fd = self.section_frame_delta(data, start_key, end_key)
        if fd is None or fd <= 0 or not self.fps:
            return None
        return fd / float(self.fps)

    def section_distance_by_virtual_lane(self, data, start_key: str, end_key: str):
        """
        시작시점→접촉시점 실제거리 위에 가상 진행선/가상차선을 놓고,
        각 시점 사이의 프레임 비율로 구간거리를 산정한다.

        차선이 화면에서 끊기거나 일부가 비어 있어도 시작-접촉 실제거리만 맞으면
        공주구간·제동구간 거리는 같은 기준선에서 일관되게 나뉜다.
        """
        if not data.get("a") or not data.get("b_contact"):
            return None, "시작/접촉시점 없음"
        if data.get("distance_ab_m") is None:
            return None, "시작-접촉 실제거리 없음"
        if not data.get(start_key) or not data.get(end_key):
            return None, "구간 시점 없음"

        a_frame = self.get_point_frame(data, "a")
        b_frame = self.get_point_frame(data, "b_contact")
        s_frame = self.get_point_frame(data, start_key)
        e_frame = self.get_point_frame(data, end_key)

        if a_frame is None or b_frame is None or s_frame is None or e_frame is None:
            return None, "시점 프레임값 없음"

        total_frames = b_frame - a_frame
        section_frames = e_frame - s_frame

        if total_frames <= 0:
            return None, "시작-접촉 프레임차 오류"
        if section_frames < 0:
            return None, "구간 프레임 순서 오류"

        distance_m = float(data["distance_ab_m"]) * (float(section_frames) / float(total_frames))
        return max(0.0, distance_m), "가상차선/프레임비"

    def compute_deceleration_mps2(self):
        mu = float(self.friction_mu_spin.value()) if hasattr(self, "friction_mu_spin") else 0.7
        long_deg = float(self.longitudinal_grade_spin.value()) if hasattr(self, "longitudinal_grade_spin") else 0.0
        cross_deg = float(self.cross_grade_spin.value()) if hasattr(self, "cross_grade_spin") else 0.0
        g = 9.80665
        long_rad = math.radians(long_deg)
        cross_rad = math.radians(cross_deg)
        effective_mu = max(0.001, mu * math.cos(cross_rad))
        decel_mps2 = g * (effective_mu * math.cos(long_rad) + math.sin(long_rad))
        return max(0.05, decel_mps2), effective_mu, mu, long_deg, cross_deg

    def estimate_reaction_distance_m(self, data):
        """
        공주시점→제동시점 거리 산출.

        1순위: 좌표투영거리
        2순위: 프레임비 거리
        3순위: 시작-접촉 전체거리와 프레임차 비율로 직접 보정

        블랙박스에서는 같은 화면 기준점을 찍으면 좌표투영거리가 0이 될 수 있으므로,
        0 또는 음수에 가까운 값은 실패로 보고 프레임 기준 거리로 보정한다.
        """
        method = "검증불가"
        distance = None

        # 1) 좌표투영거리
        try:
            d_proj = self.estimate_interval_distance_by_ab_projection(data, "reaction_start", "brake_start")
            if d_proj is not None and float(d_proj) > 0.05:
                return float(d_proj), "좌표투영거리"
        except Exception:
            pass

        # 2) 기존 프레임비 거리
        try:
            d_ratio = self.estimate_interval_distance_by_ab_ratio(data, "reaction_start", "brake_start")
            if d_ratio is not None and float(d_ratio) > 0.05:
                return float(d_ratio), "프레임비 거리"
        except Exception:
            pass

        # 3) 직접 프레임비 보정
        try:
            if not data.get("a") or not data.get("b_contact"):
                return None, method
            if data.get("distance_ab_m") is None:
                return None, method

            a_frame = self.get_point_frame(data, "a")
            b_frame = self.get_point_frame(data, "b_contact")
            r_frame = self.get_point_frame(data, "reaction_start")
            br_frame = self.get_point_frame(data, "brake_start")

            if None in (a_frame, b_frame, r_frame, br_frame):
                return None, "시점 프레임값 없음"

            ab_frames = b_frame - a_frame
            rb_frames = br_frame - r_frame

            if ab_frames <= 0 or rb_frames <= 0:
                return None, method

            d = float(data["distance_ab_m"]) * (float(rb_frames) / float(ab_frames))
            if d > 0.05:
                return d, "시작-접촉 프레임비 보정"
        except Exception:
            pass

        return None, method

    def calculate_interval_speed_by_projection(self, data, start_key: str, end_key: str):
        """
        좌표투영거리 / 프레임 시간차로 구간 평균속도(km/h)를 산출한다.
        제동시점 속도 산출용.
        """
        if not data.get(start_key) or not data.get(end_key):
            return None, None, None

        sf = self.get_point_frame(data, start_key)
        ef = self.get_point_frame(data, end_key)
        if sf is None or ef is None:
            return None, None, None

        frame_delta = ef - sf
        if frame_delta <= 0 or not self.fps:
            return None, None, None

        distance_m = self.estimate_interval_distance_by_ab_projection(data, start_key, end_key)
        if distance_m is None:
            return None, None, None

        time_s = frame_delta / self.fps
        speed_kmh = (distance_m / time_s) * 3.6 if time_s > 0 else None

        return speed_kmh, distance_m, time_s

    def estimate_interval_distance_by_ab_ratio(self, data, start_key: str, end_key: str):
        """
        현재 시작-접촉 차선계수 거리와 프레임비를 이용한 구간거리 보조추정.
        별도 구간별 차선 자동계수는 이후 정교화 대상이다.
        """
        if not data.get(start_key) or not data.get(end_key):
            return None
        if not data.get("a") or not data.get("b_contact") or data.get("distance_ab_m") is None:
            return None

        ab_frames = self.get_point_frame(data, "b_contact") - self.get_point_frame(data, "a")
        if ab_frames <= 0:
            return None

        section_frames = int(data[end_key]["frame"]) - int(data[start_key]["frame"])
        if section_frames < 0:
            return None

        return float(data["distance_ab_m"]) * (float(section_frames) / float(ab_frames))

    def safe_num(self, value, decimals=1, suffix=""):
        try:
            if value is None or value == "":
                return "검증불가"
            v = float(value)
            if not math.isfinite(v):
                return "검증불가"
            return f"{v:.{decimals}f}{suffix}"
        except Exception:
            return "검증불가"

    def safe_speed_text(self, value):
        try:
            if value is None or value == "":
                return "검증불가"
            v = float(value)
            if not math.isfinite(v):
                return "검증불가"
            return f"{v:.1f}km/h"
        except Exception:
            return "검증불가"

    def calculate_yaw_geometry_virtual_lane(self, data, fallback_geo=None):
        """
        피양거리 보정 계산.

        기존 피양거리는 화면 픽셀 대각선 환산값이라 원근/기준 픽셀거리 문제로
        1km 이상 튈 수 있었다.

        수정 기준:
        - 피양거리: 피양시점→피양 후 시점 프레임비 거리
        - 횡이동거리: 좌표 기반 횡방향 이동량을 합리 범위로 방어
        - 피양각도: atan2(횡이동거리, 피양거리)
        """
        if fallback_geo is None:
            fallback_geo = {}

        result = dict(fallback_geo)

        yaw_distance_m, yaw_distance_method = self.section_distance_by_virtual_lane(data, "yaw_start", "c_yaw")
        if yaw_distance_m is None:
            yaw_distance_m = 0.0
            yaw_distance_method = "피양시점/피양후시점 없음"

        try:
            total_distance = float(data.get("distance_ab_m") or 0.0)
            if total_distance > 0 and yaw_distance_m > total_distance:
                yaw_distance_m = total_distance
                yaw_distance_method += " / 전체거리 클램프"
        except Exception:
            pass

        try:
            lateral_abs = float(fallback_geo.get("yaw_lateral_abs_m", 0.0) or 0.0)
        except Exception:
            lateral_abs = 0.0

        # 횡이동이 피양거리보다 큰 경우는 대부분 픽셀환산/원근 오류.
        if yaw_distance_m > 0 and lateral_abs > yaw_distance_m:
            lateral_abs = yaw_distance_m

        if yaw_distance_m > 0:
            yaw_angle_deg = abs(math.degrees(math.atan2(lateral_abs, yaw_distance_m)))
        else:
            yaw_angle_deg = 0.0

        result["yaw_vector_distance_m"] = yaw_distance_m
        result["yaw_lateral_abs_m"] = lateral_abs
        result["yaw_lateral_m"] = lateral_abs
        result["yaw_angle_deg"] = yaw_angle_deg
        result["yaw_distance_method"] = yaw_distance_method
        result["yaw_direction"] = result.get("yaw_direction", "피양 산출")

        return result

    def build_stopping_analysis_result(self, data, base_speed_kmh: float = None):
        """
        정지거리 분석:
        - 공주거리: 공주시점→제동시점 프레임비 거리
        - 공주시간: 공주시점→제동시점 프레임시간
        - 공주시점 속도: 공주거리 / 공주시간
        - 제동거리: 제동시점→접촉시점 프레임비 거리
        - 접촉당시 추정속도: v² = v0² - 2*a*s
        """
        required = ["a", "reaction_start", "brake_start", "b_contact"]
        if any(not data.get(k) for k in required):
            return None
        if data.get("distance_ab_m") is None:
            return None

        # 접촉시점 = 충돌시점
        data["impact_point"] = dict(data["b_contact"])

        # 프레임 순서 검증
        missing_frame_keys = self.validate_required_points_have_frames(data, ["a", "reaction_start", "brake_start", "b_contact"])
        if missing_frame_keys:
            return {
                "error": "시점 프레임값 없음: " + ", ".join(missing_frame_keys),
                "collision_assessment": "검증불가",
                "impact_speed_kmh": None,
            }

        a_frame = self.get_point_frame(data, "a")
        reaction_frame = self.get_point_frame(data, "reaction_start")
        brake_frame = self.get_point_frame(data, "brake_start")
        contact_frame = self.get_point_frame(data, "b_contact")

        if not (a_frame <= reaction_frame <= brake_frame <= contact_frame):
            return {
                "error": "프레임 순서 오류",
                "collision_assessment": "검증불가",
                "impact_speed_kmh": None,
            }

        video_reaction_time_s = self.section_time_s(data, "reaction_start", "brake_start")
        reaction_time_s = float(self.reaction_time_spin.value()) if hasattr(self, "reaction_time_spin") else video_reaction_time_s
        braking_time_s = self.section_time_s(data, "brake_start", "b_contact")
        total_time_s = self.section_time_s(data, "reaction_start", "b_contact")

        reaction_distance_m, reaction_method = self.section_distance_by_virtual_lane(data, "reaction_start", "brake_start")
        braking_distance_m, braking_method = self.section_distance_by_virtual_lane(data, "brake_start", "b_contact")
        available_distance_m, available_method = self.section_distance_by_virtual_lane(data, "reaction_start", "b_contact")

        if reaction_time_s is None or reaction_time_s <= 0:
            return {
                "error": "공주시간 입력값 오류",
                "reaction_time_s": reaction_time_s,
                "video_reaction_time_s": video_reaction_time_s,
                "braking_time_s": braking_time_s,
                "reaction_distance_m": reaction_distance_m,
                "braking_distance_m": braking_distance_m,
                "available_distance_m": available_distance_m,
                "impact_speed_kmh": None,
                "collision_assessment": "검증불가",
                "basis": f"{reaction_method} / {braking_method}",
            }

        if reaction_distance_m is None:
            return {
                "error": "공주거리 산출불가",
                "reaction_time_s": reaction_time_s,
                "video_reaction_time_s": video_reaction_time_s,
                "braking_time_s": braking_time_s,
                "reaction_distance_m": reaction_distance_m,
                "braking_distance_m": braking_distance_m,
                "available_distance_m": available_distance_m,
                "impact_speed_kmh": None,
                "collision_assessment": "검증불가",
                "basis": f"{reaction_method} / {braking_method}",
            }

        # 공주시점과 제동시점은 같을 수 있다.
        # 이 경우 공주거리 자체는 두 점 사이 거리로는 0이지만,
        # 공주시점 속도는 시작시점→공주시점 구간에서 산출하고,
        # 공주거리는 그 속도 × 입력 공주시간으로 계산한다.
        reaction_speed_kmh = None
        same_reaction_brake = self.get_point_frame(data, "reaction_start") == self.get_point_frame(data, "brake_start")

        if reaction_distance_m is not None and float(reaction_distance_m) > 0:
            reaction_speed_kmh = self.valid_positive_speed_kmh((float(reaction_distance_m) / reaction_time_s) * 3.6)
            reaction_method_used = reaction_method
        elif same_reaction_brake:
            pre_distance_m, pre_method = self.section_distance_by_virtual_lane(data, "a", "reaction_start")
            pre_time_s = self.section_time_s(data, "a", "reaction_start")

            if pre_distance_m is not None and pre_time_s is not None and pre_time_s > 0:
                reaction_speed_kmh = self.valid_positive_speed_kmh((float(pre_distance_m) / pre_time_s) * 3.6)
                if reaction_speed_kmh is not None:
                    reaction_distance_m = (reaction_speed_kmh / 3.6) * reaction_time_s
                    reaction_method_used = f"공주=제동 동일시점: 시작→공주시점 속도 기준, 공주거리=속도×공주시간({pre_method})"
                else:
                    reaction_method_used = "공주=제동 동일시점: 시작→공주시점 속도 산출불가"
            else:
                reaction_method_used = "공주=제동 동일시점: 시작→공주시점 구간 부족"
        else:
            reaction_method_used = reaction_method

        if reaction_speed_kmh is None:
            return {
                "error": "공주시점 속도 산출불가",
                "reaction_time_s": reaction_time_s,
                "video_reaction_time_s": video_reaction_time_s,
                "braking_time_s": braking_time_s,
                "reaction_distance_m": reaction_distance_m,
                "braking_distance_m": braking_distance_m,
                "available_distance_m": available_distance_m,
                "impact_speed_kmh": None,
                "collision_assessment": "검증불가",
                "basis": f"{reaction_method_used} / {braking_method}",
            }

        decel_mps2, effective_mu, mu, long_deg, cross_deg = self.compute_deceleration_mps2()

        v0 = reaction_speed_kmh / 3.6
        braking_distance_m = float(braking_distance_m or 0.0)
        remaining_v2 = v0 * v0 - 2.0 * decel_mps2 * braking_distance_m

        if remaining_v2 <= 0:
            impact_speed_kmh = 0.0
            collision_text = "계산상 접촉 전 정지 가능"
            avoidable = True
        else:
            impact_speed_kmh = math.sqrt(remaining_v2) * 3.6
            if not math.isfinite(impact_speed_kmh):
                impact_speed_kmh = None
                collision_text = "검증불가"
                avoidable = None
            elif impact_speed_kmh > 1.0:
                collision_text = "제동 및 피양에도 접촉 가능성 높음"
                avoidable = False
            else:
                collision_text = "계산상 접촉 전 정지 가능"
                avoidable = True

        total_stop_distance_m = float(reaction_distance_m or 0.0) + float(braking_distance_m or 0.0)
        available_distance_m = total_stop_distance_m
        required_braking_distance_m = (v0 * v0) / (2.0 * decel_mps2) if decel_mps2 > 0 else None
        required_stop_distance_m = float(reaction_distance_m or 0.0) + float(required_braking_distance_m or 0.0)

        return {
            "reaction_time_s": reaction_time_s,
            "video_reaction_time_s": video_reaction_time_s,
            "braking_time_s": braking_time_s,
            "total_time_s": total_time_s,
            "base_speed_kmh": reaction_speed_kmh,
            "reaction_speed_kmh": reaction_speed_kmh,
            "reaction_distance_m": reaction_distance_m,
            "braking_distance_m": braking_distance_m,
            "available_distance_m": available_distance_m,
            "total_stop_distance_m": total_stop_distance_m,
            "mu": mu,
            "effective_mu": effective_mu,
            "longitudinal_grade_deg": long_deg,
            "cross_grade_deg": cross_deg,
            "decel_mps2": decel_mps2,
            "required_braking_distance_m": required_braking_distance_m,
            "required_stop_distance_m": required_stop_distance_m,
            "impact_speed_kmh": impact_speed_kmh,
            "collision_assessment": collision_text,
            "avoidable": avoidable,
            "basis": f"공주거리={reaction_method_used}, 공주시간=입력값 {self.safe_num(reaction_time_s, 1, 's')}, 영상상 공주시간={self.safe_num(video_reaction_time_s, 2, 's')}, 제동거리={braking_method}, 차선 공백구간은 가상차선/프레임비로 보정"
                     + (f", {self.speed_review_note(reaction_speed_kmh)}" if self.speed_review_note(reaction_speed_kmh) else ""),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }


    def calculate_stopping_analysis(self):
        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        required_keys = ["reaction_start", "brake_start", "b_contact"]
        missing = [k for k in required_keys if not data.get(k)]
        if missing:
            QMessageBox.warning(self, "확인", "제동시점, 접촉시점을 모두 찍어야 합니다. 접촉시점은 접촉시점으로 자동 사용됩니다.")
            return

        # 접촉시점 = 접촉시점
        data["impact_point"] = dict(data["b_contact"])

        speed_kmh = self.current_ab_speed_kmh(data)
        if speed_kmh is None:
            QMessageBox.warning(self, "확인", "먼저 시작-접촉거리와 시작/접촉 속도 계산 기준을 만들어야 합니다.")
            return

        rs = data["reaction_start"]
        bs = data["brake_start"]
        ip = data["impact_point"]

        if not (int(rs["frame"]) <= int(bs["frame"]) <= int(ip["frame"])):
            QMessageBox.warning(self, "확인", "프레임 순서는 제동시점 ≤ 접촉시점이어야 합니다.")
            return

        reaction_time_s = float(self.reaction_time_spin.value())
        mu = float(self.friction_mu_spin.value())
        long_deg = float(self.longitudinal_grade_spin.value())
        cross_deg = float(self.cross_grade_spin.value())
        mass_kg = float(self.vehicle_weight_spin.value())

        g = 9.80665
        v0 = speed_kmh / 3.6

        # 공주거리: 사용자가 입력한 공주시간 기준
        reaction_distance_m = v0 * reaction_time_s

        # 영상 기반 구간거리 보조추정. 현재는 시작-접촉 차선계수거리의 프레임비 기반.
        reaction_video_distance_m = self.estimate_interval_distance_by_ab_ratio(data, "reaction_start", "brake_start")
        braking_distance_m = self.estimate_interval_distance_by_ab_ratio(data, "brake_start", "b_contact")
        available_distance_m = self.estimate_interval_distance_by_ab_ratio(data, "reaction_start", "b_contact")

        if braking_distance_m is None or available_distance_m is None:
            QMessageBox.warning(self, "확인", "정지거리 분석에는 시작-접촉거리와 감속시작/충격 프레임이 필요합니다.")
            return

        long_rad = math.radians(long_deg)
        cross_rad = math.radians(cross_deg)

        # 종단경사: +는 오르막, -는 내리막.
        # 횡단경사는 법선력 감소분을 cos로 반영.
        effective_mu = max(0.001, mu * math.cos(cross_rad))
        decel_mps2 = g * (effective_mu * math.cos(long_rad) + math.sin(long_rad))
        if decel_mps2 <= 0.05:
            decel_mps2 = 0.05

        theoretical_braking_distance_m = (v0 * v0) / (2.0 * decel_mps2)
        required_stop_distance_m = reaction_distance_m + theoretical_braking_distance_m

        # 실제 영상상 제동거리에서 남는 접촉속도 추정
        remaining_v2 = max(0.0, v0 * v0 - 2.0 * decel_mps2 * braking_distance_m)
        impact_speed_kmh = math.sqrt(remaining_v2) * 3.6
        if impact_speed_kmh > 250.0 or not math.isfinite(impact_speed_kmh):
            impact_speed_kmh = 0.0

        total_stop_distance_m = reaction_distance_m + braking_distance_m
        avoidable = required_stop_distance_m <= available_distance_m
        collision_text = "제동 시 접촉회피 가능성 있음" if avoidable else "제동해도 접촉 가능성 높음"

        weight_n = mass_kg * g
        kinetic_energy_j = 0.5 * mass_kg * v0 * v0
        braking_force_n = mass_kg * decel_mps2

        result = {
            "reaction_time_s": reaction_time_s,
            "base_speed_kmh": speed_kmh,
            "reaction_distance_m": reaction_distance_m,
            "reaction_video_distance_m": reaction_video_distance_m,
            "braking_distance_m": braking_distance_m,
            "available_distance_m": available_distance_m,
            "total_stop_distance_m": total_stop_distance_m,
            "mu": mu,
            "effective_mu": effective_mu,
            "longitudinal_grade_deg": long_deg,
            "cross_grade_deg": cross_deg,
            "vehicle_weight_kg": mass_kg,
            "decel_mps2": decel_mps2,
            "theoretical_braking_distance_m": theoretical_braking_distance_m,
            "required_stop_distance_m": required_stop_distance_m,
            "impact_speed_kmh": impact_speed_kmh,
            "collision_assessment": collision_text,
            "weight_n": weight_n,
            "kinetic_energy_j": kinetic_energy_j,
            "braking_force_n": braking_force_n,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "basis": "공주거리=기준속도×입력공주시간, 제동거리=영상 프레임비 기반 시작-접촉 차선계수거리 보조추정, 제동성능=μ·경사 반영",
        }
        data["stop_analysis"] = result

        txt = (
            f"정지거리 분석 | 기준속도 {speed_kmh:.1f}km/h | "
            f"공주거리 {reaction_distance_m:.1f}m"
        )
        if reaction_video_distance_m is not None:
            txt += f" / 영상상 공주구간 {reaction_video_distance_m:.1f}m"
        txt += (
            f" | 제동거리 {braking_distance_m:.1f}m | 총 정지거리 {total_stop_distance_m:.1f}m | "
            f"필요정지거리 {required_stop_distance_m:.1f}m | 추정 접촉속도 {impact_speed_kmh:.1f}km/h | {collision_text}"
        )
        self.stop_result_label.setText(txt)
        self.statusBar().showMessage(txt)

        # 표 표시 보장:
        # 기존에는 속도 계산 결과가 이미 있을 때만 stop_analysis를 붙였기 때문에,
        # 판독시작만 누르면 표에 감속시작/정지거리가 안 나왔다.
        # 이제 기존 속도 결과가 있으면 갱신하고, 없으면 정지거리 분석용 결과행을 새로 만든다.
        target_row = None
        for r in reversed(self.speed_results):
            if r.get("vehicle") == v:
                target_row = r
                break

        if target_row is None:
            # 최소 속도 결과행 생성
            frame_delta = self.get_point_frame(data, "b_contact") - self.get_point_frame(data, "a") if data.get("a") and data.get("b_contact") else 0
            time_s = frame_delta / self.fps if frame_delta > 0 and self.fps else 0.0
            distance_ab_m = float(data.get("distance_ab_m") or 0.0)

            target_row = {
                "no": len(self.speed_results) + 1,
                "vehicle": v,
                "a": dict(data["a"]) if data.get("a") else {"frame": 0, "timecode": "", "x": 0, "y": 0},
                "b_contact": dict(data["b_contact"]) if data.get("b_contact") else {"frame": 0, "timecode": "", "x": 0, "y": 0},
                "yaw_start": dict(data.get("yaw_start")) if data.get("yaw_start") else None,
                "c_yaw": dict(data.get("c_yaw")) if data.get("c_yaw") else None,
                "frame_delta": frame_delta,
                "time_delta_s": time_s,
                "distance_ab_m": distance_ab_m,
                "speed_ab_kmh": speed_kmh,
                "yaw_vector_distance_m": 0.0,
                "yaw_vector_speed_kmh": 0.0,
                "yaw_longitudinal_m": 0.0,
                "yaw_lateral_m": 0.0,
                "yaw_lateral_abs_m": 0.0,
                "yaw_angle_deg": 0.0,
                "yaw_angle_signed_deg": None,
                "yaw_direction": "",
                "basis": "정지거리 분석용 자동 생성 행",
                "distance_evidence": data.get("distance_evidence", ""),
                "remark": "정지거리 분석",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.speed_results.append(target_row)

        target_row["stop_analysis"] = dict(result)
        target_row["reaction_distance_m"] = reaction_distance_m
        target_row["braking_distance_m"] = braking_distance_m
        target_row["total_stop_distance_m"] = total_stop_distance_m
        target_row["impact_speed_kmh"] = impact_speed_kmh
        target_row["remark"] = (
            f"정지거리 분석 / 공주 {reaction_distance_m:.1f}m / "
            f"제동 {braking_distance_m:.1f}m / 총 {total_stop_distance_m:.1f}m / "
            f"접촉속도 {impact_speed_kmh:.1f}km/h / {collision_text}"
        )
        self.refresh_speed_table()

        # 판독/보고서 탭 자동 작성
        self.update_report_note_from_result(target_row)

        QMessageBox.information(
            self,
            "정지거리 분석 완료",
            f"기준속도: {speed_kmh:.1f} km/h\n"
            f"공주시간: {reaction_time_s:.1f} s\n"
            f"공주거리: {reaction_distance_m:.1f} m\n"
            f"영상상 공주구간 추정: {reaction_video_distance_m:.1f} m\n"
            f"영상상 제동거리: {braking_distance_m:.1f} m\n"
            f"총 정지거리: {total_stop_distance_m:.1f} m\n"            f"표시값: 공주거리/제동거리/정지거리 표 반영 완료\n\n"
            f"노면마찰계수 μ: {mu:.1f}\n"
            f"유효마찰계수: {effective_mu:.1f}\n"
            f"종단경사: {long_deg:.1f}° / 횡단경사: {cross_deg:.1f}°\n"
            f"차량중량: {mass_kg:.0f} kg\n"
            f"감속도: {decel_mps2:.1f} m/s²\n"
            f"이론 제동거리: {theoretical_braking_distance_m:.1f} m\n"
            f"필요정지거리: {required_stop_distance_m:.1f} m\n"
            f"추정 접촉속도: {impact_speed_kmh:.1f} km/h\n\n"
            f"판정: {collision_text}\n\n"
            "참고: 차량중량은 운동에너지/제동력 계산에 표시되며, 이상적인 마찰제동거리 자체는 질량이 상쇄됩니다."
        )

    def valid_positive_speed_kmh(self, value):
        """
        공주시점 속도 산출용.
        일반적인 비현실 상한으로 값을 죽이지 않는다.
        유한한 양수면 표시하고, 비정상 고속 여부는 비고에서 따로 경고한다.
        """
        try:
            v = float(value)
            if not math.isfinite(v):
                return None
            if v <= 0:
                return None
            return v
        except Exception:
            return None

    def speed_review_note(self, value):
        try:
            v = float(value)
            if not math.isfinite(v):
                return "속도값 검증불가"
            if v > 250:
                return "공주시점 속도 250km/h 초과: 거리/공주시간/시점 재검토 필요"
            if v < 1:
                return "공주시점 속도 1km/h 미만: 공주/제동 시점 재검토 필요"
            return ""
        except Exception:
            return "속도값 검증불가"

    def sanitize_vehicle_speed_kmh(self, value, label: str = "속도"):
        """
        일반 승용차 블랙박스 판독에서 비현실적인 속도값이 표에 들어가는 것을 차단한다.
        계산값 자체가 0 미만, NaN, 무한대, 250km/h 초과면 None 처리한다.
        """
        try:
            v = float(value)
        except Exception:
            return None

        if not math.isfinite(v):
            return None
        if v < 0:
            return None
        if v > 250.0:
            return None
        return v

    def compose_basic_opinion_report(self, result: dict) -> str:
        """
        판독/보고서 기본 문안 자동작성.
        """
        stop = result.get("stop_analysis") or {}

        def n(value, default=None):
            try:
                if value is None or value == "":
                    return default
                return float(value)
            except Exception:
                return default

        def d(value, suffix=" m"):
            if value is None:
                return "검증불가"
            try:
                return f"{float(value):.1f}{suffix}"
            except Exception:
                return "검증불가"

        reaction_speed = n(result.get("speed_ab_kmh", stop.get("reaction_speed_kmh")))
        impact_speed = n(stop.get("impact_speed_kmh", result.get("impact_speed_kmh")))
        reaction_distance = n(stop.get("reaction_distance_m", result.get("reaction_distance_m")))
        braking_distance = n(stop.get("braking_distance_m", result.get("braking_distance_m")))
        total_stop_distance = n(stop.get("total_stop_distance_m", result.get("total_stop_distance_m")))
        available_distance = n(stop.get("available_distance_m"))
        yaw_angle = n(result.get("yaw_angle_deg", 0.0), 0.0)
        lateral_distance = n(result.get("yaw_lateral_abs_m", 0.0), 0.0)
        reaction_time = n(stop.get("reaction_time_s", result.get("reaction_time_s")))
        video_reaction_time = n(stop.get("video_reaction_time_s", result.get("video_reaction_time_s")))
        braking_time = n(stop.get("braking_time_s", result.get("braking_time_s")))
        contact_time = (result.get("b_contact") or {}).get("timecode", "")

        if impact_speed is None:
            final_sentence = "따라서 접촉당시 추정속도가 검증불가이므로, 적극적인 제동과 피양을 실시했을 때 사고를 피할 수 있었는지는 단정할 수 없다."
        elif impact_speed <= 1.0:
            final_sentence = "따라서 이미 대차(또는 대인)을 인지했을 시점에서 적극적인 제동과 피양을 실시했을 때 사고를 피할 수 있는 가능성이 있었다."
        else:
            final_sentence = "따라서 이미 대차(또는 대인)을 인지했을 시점에서 적극적인 제동과 피양을 실시했어도 접촉당시 추정속도가 1km/h를 초과하므로 사고를 피하기 어려웠을 가능성이 높다."

        report = (
            f"적용 시작-접촉거리 : {d(result.get('distance_ab_m'))}\n"
            f"공주시점 속도 : {d(reaction_speed, ' km/h')}\n"
            f"충돌시점 시간 : {contact_time or '검증불가'}\n"
            f"공주시간(입력값) : {d(reaction_time, ' s')}\n"
            f"영상상 공주시간(참고) : {d(video_reaction_time, ' s')}\n"
            f"제동시간 : {d(braking_time, ' s')}\n"
            f"공주거리 : {d(reaction_distance)}\n"
            f"제동거리 : {d(braking_distance)}\n"
            f"정지거리 : {d(total_stop_distance)}\n"
            f"공주시점에서 접촉시점까지의 거리 : {d(available_distance)}\n"
            f"피양거리 : {d(result.get('yaw_vector_distance_m'))}\n"
            f"피양 각도(횡이동) : {d(yaw_angle, '°')} / 횡이동 {d(lateral_distance)}\n"
            f"접촉당시 추정속도 : {d(impact_speed, ' km/h')}\n"
            f"{final_sentence}\n"
        )

        return report


    def update_report_note_from_result(self, result: dict):
        """
        판독 결과를 판독/보고서 탭에 자동 반영한다.
        """
        report = self.compose_basic_opinion_report(result)

        if hasattr(self, "report_note") and self.report_note is not None:
            self.report_note.setPlainText(report)

        return report

    def start_full_analysis(self):
        """
        판독시작:
        하나의 버튼으로 속도, 피양각, 정지거리 분석을 실행한다.
        - 시작시점/접촉시점/시작-접촉거리는 필수
        - 피양시점/피양 후 시점이 있으면 피양각 계산
        - 제동시점/제동시점이 있으면 정지거리 계산
        - 접촉시점은 접촉시점으로 자동 사용
        """
        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        if data.get("b_contact"):
            data["impact_point"] = dict(data["b_contact"])

        # 판독 전 현재 화면의 시작-접촉 실제거리 값을 계산용 데이터에 강제 동기화한다.
        self.sync_distance_from_ui(clear_previous=True)

        missing = []
        if not data.get("a"):
            missing.append("시작시점")
        if not data.get("b_contact"):
            missing.append("접촉시점")
        if data.get("distance_ab_m") is None:
            missing.append("시작-접촉거리")
        if not data.get("reaction_start"):
            missing.append("공주시점")
        if not data.get("brake_start"):
            missing.append("제동시점")

        if missing:
            QMessageBox.warning(
                self,
                "판독 불가",
                "판독시작 전에 아래 항목이 필요합니다.\n\n- " + "\n- ".join(missing)
            )
            return

        try:
            self.calculate_speed()
        except Exception as e:
            QMessageBox.critical(
                self,
                "판독 오류",
                f"판독 중 오류가 발생했습니다.\n\n{type(e).__name__}: {e}"
            )
            return


    def calculate_speed(self):
        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]

        # 계산 직전 현재 입력된 시작-접촉 실제거리를 다시 읽는다.
        applied_distance_now = self.sync_distance_from_ui(clear_previous=True)
        self.clear_speed_results_for_vehicle(v)

        required = [
            ("a", "시작시점"),
            ("reaction_start", "공주시점"),
            ("brake_start", "제동시점"),
            ("b_contact", "접촉시점"),
        ]
        missing = [name for key, name in required if not data.get(key)]
        if data.get("distance_ab_m") is None:
            missing.append("시작-접촉 실제거리")

        if missing:
            QMessageBox.warning(self, "확인", "판독에 필요한 시점/거리가 빠졌습니다.\n\n- " + "\n- ".join(missing))
            return

        missing_frame_keys = self.validate_required_points_have_frames(data, ["a", "reaction_start", "brake_start", "b_contact"])
        if missing_frame_keys:
            QMessageBox.warning(
                self,
                "시점 프레임값 없음",
                "아래 시점에 프레임값이 없습니다. 다시 찍어주세요.\n\n- " + "\n- ".join(missing_frame_keys)
            )
            return

        a_frame = self.get_point_frame(data, "a")
        reaction_frame = self.get_point_frame(data, "reaction_start")
        brake_frame = self.get_point_frame(data, "brake_start")
        contact_frame = self.get_point_frame(data, "b_contact")

        if not (a_frame <= reaction_frame <= brake_frame <= contact_frame):
            QMessageBox.warning(
                self,
                "프레임 순서 오류",
                "시점 순서가 맞지 않습니다.\n\n"
                "시작시점 ≤ 공주시점 ≤ 제동시점 ≤ 접촉시점 순서로 찍어주세요. 공주시점과 제동시점은 같은 프레임이어도 됩니다."
            )
            return

        data["impact_point"] = dict(data["b_contact"])

        stop_auto = self.build_stopping_analysis_result(data)
        if not stop_auto or stop_auto.get("error"):
            err = (stop_auto or {}).get("error", "계산 실패")
            QMessageBox.warning(self, "판독 불가", f"{err}\n\n시작-접촉 실제거리와 각 시점 프레임을 다시 확인하세요.")
            return

        speed_ab_kmh = stop_auto.get("reaction_speed_kmh")
        reaction_time_s = stop_auto.get("reaction_time_s")
        braking_time_s = stop_auto.get("braking_time_s")
        distance_ab_m = float(data["distance_ab_m"])
        frame_delta = contact_frame - a_frame
        time_s = frame_delta / self.fps if self.fps else None

        # 피양각은 피양시점/피양 후 시점이 있을 때만 계산한다.
        yaw_available = bool(data.get("yaw_start") and data.get("c_yaw"))
        if yaw_available:
            try:
                raw_geo = self.calculate_lateral_geometry(
                    data["a"], data["b_contact"], data.get("yaw_start"), data["c_yaw"], distance_ab_m
                )
            except Exception:
                raw_geo = {
                    "yaw_vector_distance_m": 0.0,
                    "yaw_lateral_abs_m": 0.0,
                    "yaw_angle_deg": 0.0,
                    "yaw_angle_signed_deg": None,
                    "yaw_direction": "피양각 검증불가",
                    "yaw_frame_gap": None,
                }
            geo = self.calculate_yaw_geometry_virtual_lane(data, raw_geo)
        else:
            geo = {
                "yaw_vector_distance_m": 0.0,
                "yaw_lateral_abs_m": 0.0,
                "yaw_angle_deg": 0.0,
                "yaw_angle_signed_deg": None,
                "yaw_direction": "피양각 미산출",
                "yaw_frame_gap": None,
                "yaw_distance_method": "",
            }

        impact_speed = stop_auto.get("impact_speed_kmh")
        impact_speed_txt = self.safe_speed_text(impact_speed)

        remark = (
            f"적용 시작-접촉거리={self.safe_num(data.get('distance_ab_m'), 1, 'm')} / "
            f"공주시점속도={self.safe_speed_text(speed_ab_kmh)} / "
            f"공주시간입력={self.safe_num(reaction_time_s, 1, 's')} / "
            f"영상공주시간={self.safe_num(stop_auto.get('video_reaction_time_s'), 2, 's')} / "
            f"제동시간={self.safe_num(braking_time_s, 2, 's')} / "
            f"접촉당시 추정속도={impact_speed_txt} / "
            f"{stop_auto.get('collision_assessment', '')} / "
            f"{stop_auto.get('basis', '')}"
        )

        if yaw_available:
            remark += f" / 피양거리 {self.safe_num(geo.get('yaw_vector_distance_m'), 1, 'm')}({geo.get('yaw_distance_method', '가상차선/프레임비')}) / 피양각 {self.safe_num(geo.get('yaw_angle_deg'), 1, '°')}"
        else:
            remark += " / 피양 없음 또는 미지정"

        result = {
            "no": len(self.speed_results) + 1,
            "vehicle": v,
            "a": dict(data["a"]),
            "reaction_start": dict(data["reaction_start"]),
            "brake_start": dict(data["brake_start"]),
            "b_contact": dict(data["b_contact"]),
            "yaw_start": dict(data.get("yaw_start")) if data.get("yaw_start") else None,
            "c_yaw": dict(data.get("c_yaw")) if data.get("c_yaw") else None,
            "frame_delta": frame_delta,
            "time_delta_s": time_s,
            "reaction_time_s": reaction_time_s,
            "video_reaction_time_s": stop_auto.get("video_reaction_time_s"),
            "braking_time_s": braking_time_s,
            "distance_ab_m": distance_ab_m,
            "speed_ab_kmh": speed_ab_kmh,
            "reaction_speed_kmh": speed_ab_kmh,
            "yaw_vector_distance_m": geo.get("yaw_vector_distance_m", 0.0),
            "yaw_vector_speed_kmh": 0.0,
            "yaw_longitudinal_m": geo.get("yaw_longitudinal_m", 0.0),
            "yaw_lateral_m": geo.get("yaw_lateral_m", 0.0),
            "yaw_lateral_abs_m": geo.get("yaw_lateral_abs_m", 0.0),
            "yaw_angle_deg": geo.get("yaw_angle_deg", 0.0),
            "yaw_angle_signed_deg": geo.get("yaw_angle_signed_deg"),
            "yaw_direction": geo.get("yaw_direction", ""),
            "yaw_distance_method": geo.get("yaw_distance_method", ""),
            "basis": stop_auto.get("basis", ""),
            "distance_evidence": data.get("distance_evidence", ""),
            "stop_analysis": stop_auto,
            "reaction_distance_m": stop_auto.get("reaction_distance_m"),
            "braking_distance_m": stop_auto.get("braking_distance_m"),
            "total_stop_distance_m": stop_auto.get("total_stop_distance_m"),
            "impact_speed_kmh": stop_auto.get("impact_speed_kmh"),
            "remark": remark,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        data["stop_analysis"] = stop_auto

        if hasattr(self, "stop_result_label"):
            self.stop_result_label.setText(
                f"판독 완료 | 거리 {self.safe_num(data.get('distance_ab_m'), 1, 'm')} | 공주시점속도 {self.safe_speed_text(speed_ab_kmh)} | "
                f"공주 {self.safe_num(stop_auto.get('reaction_distance_m'), 1, 'm')}/{self.safe_num(reaction_time_s, 1, 's')} | "
                f"제동 {self.safe_num(stop_auto.get('braking_distance_m'), 1, 'm')}/{self.safe_num(braking_time_s, 2, 's')} | "
                f"접촉당시 {impact_speed_txt} | {stop_auto.get('collision_assessment', '')}"
            )

        self.update_report_note_from_result(result)
        self.speed_results.append(result)
        self.refresh_speed_table()

        self.statusBar().showMessage(
            f"{v} 판독 완료 | 거리 {self.safe_num(data.get('distance_ab_m'), 1, 'm')} | 공주시점속도 {self.safe_speed_text(speed_ab_kmh)} | "
            f"접촉당시 추정속도 {impact_speed_txt} | 공주시간 입력 {self.safe_num(reaction_time_s, 1, 's')}"
        )


    def get_point_frame_index(self, point):
        if not point:
            return None
        if "frame" in point:
            return int(point["frame"])
        if "marked_frame" in point:
            return int(point["marked_frame"])
        return None

    def set_preview_image(self, label: QLabel, title: str, point, mark_text: str):
        if not hasattr(self, "video_path") or not self.video_path or not point:
            label.clear()
            label.setText(f"{title}\n미지정")
            return

        frame_index = self.get_point_frame_index(point)
        if frame_index is None:
            label.clear()
            label.setText(f"{title}\n프레임 없음")
            return

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            label.clear()
            label.setText(f"{title}\n영상 열기 실패")
            return

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            label.clear()
            label.setText(f"{title}\nF{frame_index} 읽기 실패")
            return

        x, y = int(point["x"]), int(point["y"])
        cv2.circle(frame, (x, y), 16, (0, 255, 255), 3)
        cv2.line(frame, (x - 28, y), (x + 28, y), (0, 255, 255), 2)
        cv2.line(frame, (x, y - 28), (x, y + 28), (0, 255, 255), 2)
        cv2.putText(
            frame,
            mark_text,
            (x + 18, max(28, y - 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        if "timecode" in point:
            tc = point["timecode"]
        else:
            tc = point.get("marked_timecode", seconds_to_timecode(frame_index / self.fps if self.fps else 0.0))

        title_text = f"{title}  F{frame_index}  {tc}"
        cv2.rectangle(frame, (0, 0), (min(frame.shape[1] - 1, 900), 46), (0, 0, 0), -1)
        cv2.putText(
            frame,
            title_text,
            (12, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)

        label.clear()
        label.setPixmap(pix.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label.setToolTip(title_text)

    def refresh_previews(self):
        if not hasattr(self, "preview_a"):
            return

        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]
        self.set_preview_image(self.preview_a, "시작시점", data.get("a"), "A")
        self.set_preview_image(self.preview_b, "접촉시점", data.get("b_contact"), "B")
        if hasattr(self, "preview_y"):
            self.set_preview_image(self.preview_y, "피양시점", data.get("yaw_start"), "Y")
        self.set_preview_image(self.preview_c, "피양 후 시점", data.get("c_yaw"), "C")
        if hasattr(self, "preview_reaction"):
            self.set_preview_image(self.preview_reaction, "공주시점", data.get("reaction_start"), "공주")
        if hasattr(self, "preview_brake"):
            self.set_preview_image(self.preview_brake, "제동시점", data.get("brake_start"), "제동")

    def refresh_speed_status(self):
        if not hasattr(self, "status_label"):
            return

        v = self.vehicle_combo.currentText()
        data = self.vehicle_data[v]
        lines = [
            f"차량: {v}",
            f"시작시점: {point_text(data['a'])}",
            f"접촉시점: {point_text(data['b_contact'])}",
            f"피양시점: {point_text(data.get('yaw_start'))}",
            f"피양 후 시점: {point_text(data['c_yaw'])}",
            f"공주시점: {point_text(data.get('reaction_start'))}",
            f"제동시점: {point_text(data.get('brake_start'))}",
            f"시작-접촉거리: {data['distance_ab_m']:.1f}m" if data["distance_ab_m"] is not None else "시작-접촉거리: 미적용",
            f"거리근거: {data.get('distance_evidence') or '시작시점/접촉시점 차선계수 통합점 사용'}",
            f"차선계수선: {point_text(data.get('lane_line_1'))} ~ {point_text(data.get('lane_line_2'))}",
        ]
        self.status_label.setText(" | ".join(lines))
        self.refresh_previews()
        self.update_point_button_states()

    def refresh_speed_table(self):
        self.speed_table.setRowCount(len(self.speed_results))

        for row, r in enumerate(self.speed_results):
            stop = r.get("stop_analysis") or {}
            if not stop:
                stop = {
                    "reaction_distance_m": r.get("reaction_distance_m"),
                    "braking_distance_m": r.get("braking_distance_m"),
                    "total_stop_distance_m": r.get("total_stop_distance_m"),
                    "impact_speed_kmh": r.get("impact_speed_kmh"),
                }

            def fmt_num(value, decimals=3):
                if value is None or value == "":
                    return ""
                try:
                    return f"{float(value):.{decimals}f}"
                except Exception:
                    return ""

            def fmt_speed(value, text=None):
                if text:
                    return str(text)
                try:
                    if value is None or value == "":
                        return "검증불가"
                    v = float(value)
                    if not math.isfinite(v) or v < 0:
                        return "검증불가"
                    return f"{v:.1f}"
                except Exception:
                    return "검증불가"

            def fmt_reaction_speed(value):
                checked = self.valid_positive_speed_kmh(value)
                if checked is None:
                    return "검증불가"
                return f"{checked:.1f}"

            values = [
                str(row + 1),
                str(r.get("vehicle", "")),
                str((r.get("reaction_start") or {}).get("frame", "")),
                str((r.get("brake_start") or {}).get("frame", "")),
                str((r.get("b_contact") or {}).get("frame", "")),
                fmt_num(r.get("reaction_time_s", (stop or {}).get("reaction_time_s")), 2),
                fmt_num(r.get("braking_time_s", (stop or {}).get("braking_time_s")), 2),
                str((r.get("b_contact") or {}).get("timecode", "")),
                fmt_reaction_speed(r.get("speed_ab_kmh")),
                fmt_num(r.get("yaw_vector_distance_m"), 1),
                fmt_num(r.get("yaw_lateral_abs_m"), 1),
                fmt_num(r.get("yaw_angle_deg"), 1),
                fmt_num(stop.get("reaction_distance_m", r.get("reaction_distance_m", None)), 1),
                fmt_num(stop.get("braking_distance_m", r.get("braking_distance_m", None)), 1),
                fmt_num(stop.get("total_stop_distance_m", r.get("total_stop_distance_m", None)), 1),
                fmt_speed(stop.get("impact_speed_kmh", r.get("impact_speed_kmh", None))),
                str(r.get("remark", "")),
            ]

            # 열 개수가 예전 파일 상태와 달라도 맞춰서 넣는다.
            if self.speed_table.columnCount() < len(values):
                self.speed_table.setColumnCount(len(values))
                self.speed_table.setHorizontalHeaderLabels([
            "순번",
            "차량",
            "공주\n프레임",
            "제동\n프레임",
            "접촉\n프레임",
            "공주시간\n입력(s)",
            "제동\n시간(s)",
            "접촉\n시간",
            "공주시점\n속도(km/h)",
            "피양거리\n프레임비(m)",
            "횡이동\n거리(m)",
            "피양\n각도(°)",
            "공주\n거리(m)",
            "제동\n거리(m)",
            "정지\n거리(m)",
            "접촉당시\n추정속도(km/h)",
            "비고",
        ])

            for col, value in enumerate(values):
                self.speed_table.setItem(row, col, QTableWidgetItem(value))

        self.speed_table.resizeRowsToContents()


    def on_speed_double_click(self, row: int, col: int):
        if 0 <= row < len(self.speed_results):
            self.seek_frame(self.speed_results[row]["a"]["frame"])

    # ---------------- Events / Capture ----------------

    def add_event(self):
        if not self.video_path:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return
        sec = self.current_frame_index / self.fps if self.fps else 0.0
        e = {
            "no": len(self.events) + 1,
            "frame": int(self.current_frame_index),
            "time_seconds": float(sec),
            "timecode": seconds_to_timecode(sec),
            "event_type": self.event_combo.currentText(),
            "memo": self.event_memo.text().strip(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.events.append(e)
        self.event_memo.clear()
        self.refresh_event_table()

    def capture_current_frame(self):
        if self.current_frame_bgr is None or not self.output_dir:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return

        captures_dir = self.output_dir / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)

        t = seconds_to_timecode(self.current_frame_index / self.fps if self.fps else 0.0)
        filename = f"capture_F{self.current_frame_index:06d}_{t.replace(':', '-').replace('.', '_')}.jpg"
        out_path = captures_dir / filename

        frame = self.draw_overlay(self.current_frame_bgr)
        cv2.rectangle(frame, (10, max(10, frame.shape[0] - 92)), (min(frame.shape[1] - 10, 860), frame.shape[0] - 20), (0, 0, 0), -1)
        cv2.putText(frame, f"Frame: {self.current_frame_index} / Time: {t}", (24, frame.shape[0] - 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"Source: {Path(self.video_path).name}", (24, frame.shape[0] - 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)

        ok = cv2.imwrite(str(out_path), frame)
        if not ok:
            QMessageBox.critical(self, "오류", "캡처 저장 실패")
            return

        c = {
            "no": len(self.captures) + 1,
            "frame": int(self.current_frame_index),
            "timecode": t,
            "file": str(out_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.captures.append(c)
        self.refresh_capture_table()
        self.statusBar().showMessage(f"캡처 저장: {out_path}")

    def refresh_event_table(self):
        self.event_table.setRowCount(len(self.events))
        for row, e in enumerate(self.events):
            values = [str(row + 1), str(e["frame"]), e["timecode"], e["event_type"], e.get("memo", "")]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col in (0, 1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                self.event_table.setItem(row, col, item)

    def refresh_capture_table(self):
        self.capture_table.setRowCount(len(self.captures))
        for row, c in enumerate(self.captures):
            values = [str(row + 1), str(c["frame"]), c["timecode"], Path(c["file"]).name]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col in (0, 1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                self.capture_table.setItem(row, col, item)

    def refresh_all_tables(self):
        self.refresh_speed_table()
        self.refresh_event_table()
        self.refresh_capture_table()

    def on_event_double_click(self, row: int, col: int):
        if 0 <= row < len(self.events):
            self.seek_frame(self.events[row]["frame"])

    # ---------------- Export / Report ----------------

    def case_data(self):
        duration = self.total_frames / self.fps if self.fps else 0.0
        return {
            "app": APP_NAME,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "video_path": self.video_path,
            "video_name": Path(self.video_path).name if self.video_path else "",
            "video_hash_sha256": self.video_hash,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "duration_seconds": duration,
            "duration_timecode": seconds_to_timecode(duration),
            "width": self.width,
            "height": self.height,
            "vehicle_data": self.vehicle_data,
            "speed_results": self.speed_results,
            "events": self.events,
            "captures": self.captures,
            "report_note": self.report_note.toPlainText().strip(),
        }

    def export_speed_csv(self):
        if not self.output_dir:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return

        path = self.output_dir / "speed_results.csv"
        self.write_speed_csv(path)
        QMessageBox.information(self, "완료", f"속도 CSV 저장 완료\n{path}")

    def write_speed_csv(self, path: Path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "no",
                "vehicle",
                "a_frame",
                "b_contact_frame",
                "a_timecode",
                "b_contact_timecode",
                "frame_delta",
                "time_delta_s",
                "distance_ab_m",
                "speed_ab_kmh",
                "yaw_vector_distance_m",
                "yaw_lateral_m",
                "yaw_angle_deg_abs",
                "yaw_angle_signed_deg",
                "yaw_direction",
                "basis",
                "distance_evidence",
                "reaction_time_s",
                "reaction_distance_m",
                "braking_distance_m",
                "total_stop_distance_m",
                "required_stop_distance_m",
                "impact_speed_kmh",
                "mu",
                "effective_mu",
                "longitudinal_grade_deg",
                "cross_grade_deg",
                "vehicle_weight_kg",
                "collision_assessment",
                "remark",
                "created_at",
            ])
            for i, r in enumerate(self.speed_results, start=1):
                writer.writerow([
                    i,
                    r["vehicle"],
                    r["a"]["frame"],
                    r["b_contact"]["frame"],
                    r["a"]["timecode"],
                    r["b_contact"]["timecode"],
                    r["frame_delta"],
                    f"{r['time_delta_s']:.1f}",
                    f"{r['distance_ab_m']:.1f}",
                    f"{r['speed_ab_kmh']:.1f}",
                    f"{r['yaw_vector_distance_m']:.1f}",
                    f"{r['yaw_lateral_m']:.1f}",
                    f"{r['yaw_angle_deg']:.1f}",
                    f"{r.get('yaw_angle_signed_deg', 0.0):.1f}" if r.get("yaw_angle_signed_deg") is not None else "",
                    r.get("yaw_direction", ""),
                    r["basis"],
                    r.get("distance_evidence", ""),
                    (r.get("stop_analysis") or {}).get("reaction_time_s", ""),
                    (r.get("stop_analysis") or {}).get("reaction_distance_m", ""),
                    (r.get("stop_analysis") or {}).get("braking_distance_m", ""),
                    (r.get("stop_analysis") or {}).get("total_stop_distance_m", ""),
                    (r.get("stop_analysis") or {}).get("required_stop_distance_m", ""),
                    (r.get("stop_analysis") or {}).get("impact_speed_kmh", ""),
                    (r.get("stop_analysis") or {}).get("mu", ""),
                    (r.get("stop_analysis") or {}).get("effective_mu", ""),
                    (r.get("stop_analysis") or {}).get("longitudinal_grade_deg", ""),
                    (r.get("stop_analysis") or {}).get("cross_grade_deg", ""),
                    (r.get("stop_analysis") or {}).get("vehicle_weight_kg", ""),
                    (r.get("stop_analysis") or {}).get("collision_assessment", ""),
                    r.get("remark", ""),
                    r.get("created_at", ""),
                ])

    def generate_html_report(self):
        if not self.video_path or not self.output_dir:
            QMessageBox.warning(self, "확인", "먼저 영상을 열어주세요.")
            return

        data = self.case_data()
        report_path = self.output_dir / "blackbox_report.html"

        speed_rows = []
        for i, r in enumerate(self.speed_results, start=1):
            speed_rows.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{html.escape(r['vehicle'])}</td>"
                f"<td>{r['a']['frame']}</td>"
                f"<td>{r['b_contact']['frame']}</td>"
                f"<td>{html.escape(r['a']['timecode'])}</td>"
                f"<td>{html.escape(r['b_contact']['timecode'])}</td>"
                f"<td>{r['time_delta_s']:.1f}</td>"
                f"<td>{r['distance_ab_m']:.1f}</td>"
                f"<td><b>{r['speed_ab_kmh']:.1f}</b></td>"
                f"<td>{r['yaw_vector_distance_m']:.1f}</td>"
                f"<td>{r['yaw_lateral_abs_m']:.1f}</td>"
                f"<td>{r['yaw_angle_deg']:.1f}</td>"
                f"<td>{((r.get('stop_analysis') or {}).get('reaction_distance_m', 0.0)):.1f}</td>" if r.get('stop_analysis') else "<td></td>"
                f"<td>{((r.get('stop_analysis') or {}).get('braking_distance_m', 0.0)):.1f}</td>" if r.get('stop_analysis') else "<td></td>"
                f"<td>{((r.get('stop_analysis') or {}).get('total_stop_distance_m', 0.0)):.1f}</td>" if r.get('stop_analysis') else "<td></td>"
                f"<td>{((r.get('stop_analysis') or {}).get('impact_speed_kmh', 0.0)):.1f}</td>" if r.get('stop_analysis') else "<td></td>"
                f"<td>{html.escape((r.get('stop_analysis') or {}).get('collision_assessment', ''))}</td>" if r.get('stop_analysis') else "<td></td>"
                f"<td>{html.escape(r.get('remark', ''))}</td>"
                "</tr>"
            )

        event_rows = []
        for i, e in enumerate(self.events, start=1):
            event_rows.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{e['frame']}</td>"
                f"<td>{html.escape(e['timecode'])}</td>"
                f"<td>{html.escape(e['event_type'])}</td>"
                f"<td>{html.escape(e.get('memo', ''))}</td>"
                "</tr>"
            )

        capture_blocks = []
        for i, c in enumerate(self.captures, start=1):
            file_path = Path(c["file"])
            rel = os.path.relpath(file_path, self.output_dir)
            capture_blocks.append(
                "<div class='capture'>"
                f"<h3>캡처 {i} — F{c['frame']} / {html.escape(c['timecode'])}</h3>"
                f"<img src='{html.escape(rel)}'>"
                f"<p>{html.escape(file_path.name)}</p>"
                "</div>"
            )

        note = html.escape(data.get("report_note", "")).replace("\n", "<br>")

        html_doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>블랙박스 판독 리포트</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif;
    margin: 32px;
    color: #222;
}}
h1 {{ border-bottom: 3px solid #222; padding-bottom: 10px; }}
table {{ width: 100%; border-collapse: collapse; margin: 14px 0 28px 0; }}
th, td {{ border: 1px solid #aaa; padding: 8px 10px; vertical-align: top; }}
thead th {{ background: #222; color: #fff; }}
.meta th {{ width: 190px; background: #f0f0f0; color: #222; text-align: left; }}
.warn {{ border: 2px solid #b00020; color: #b00020; padding: 12px; font-weight: bold; margin: 16px 0; }}
.capture {{ page-break-inside: avoid; margin: 24px 0; }}
.capture img {{ max-width: 100%; border: 1px solid #444; }}
.small {{ color: #666; font-size: 12px; }}
.note {{ border: 1px solid #aaa; padding: 12px; min-height: 70px; background: #fafafa; }}
@media print {{ body {{ margin: 14mm; }} }}
</style>
</head>
<body>
<h1>블랙박스 판독 리포트</h1>

<div class="warn">
시작시점은 도로 시작시점과 차량 시작시점을 동시에 저장합니다.
접촉시점은 접촉지점, C는 피양 후점입니다.
자차 블랙박스는 카메라가 이동하므로 장거리 시작-접촉거리를 화면 픽셀차로 산출하지 않았습니다.
시작-접촉거리는 지도·현장실측·시설물 간격·차량자료 등 외부 근거값을 사용하고, 영상은 시간차와 피양각도 판독에 사용했습니다.
</div>

<h2>1. 원본 영상 정보</h2>
<table class="meta">
<tr><th>파일명</th><td>{html.escape(data['video_name'])}</td></tr>
<tr><th>원본 경로</th><td>{html.escape(data['video_path'])}</td></tr>
<tr><th>SHA-256</th><td class="small">{html.escape(data['video_hash_sha256'])}</td></tr>
<tr><th>해상도</th><td>{data['width']} x {data['height']}</td></tr>
<tr><th>FPS</th><td>{data['fps']:.1f}</td></tr>
<tr><th>총 프레임</th><td>{data['total_frames']:,}</td></tr>
<tr><th>재생 시간</th><td>{html.escape(data['duration_timecode'])}</td></tr>
<tr><th>리포트 생성</th><td>{html.escape(data['saved_at'])}</td></tr>
</table>

<h2>2. 속도 산출 결과</h2>
<table>
<thead>
<tr>
<th>순번</th><th>차량</th><th>공주<br>프레임</th><th>접촉<br>프레임</th><th>공주<br>시간</th><th>접촉<br>시간</th>
<th>제동<br>시간</th><th>공주시점<br>속도(km/h)</th><th>공주시점<br>속도(km/h)</th><th>피양<br>거리(m)</th>
<th>횡이동<br>거리(m)</th><th>피양<br>각도(°)</th>
<th>공주<br>거리(m)</th><th>제동<br>거리(m)</th><th>정지<br>거리(m)</th><th>접촉당시<br>추정속도(km/h)</th><th>접촉가능성</th><th>비고</th>
</tr>
</thead>
<tbody>
{''.join(speed_rows) if speed_rows else '<tr><td colspan="18">기록된 속도 산출값 없음</td></tr>'}
</tbody>
</table>

<h2>3. 주요 이벤트 타임라인</h2>
<table>
<thead>
<tr><th>순번</th><th>프레임</th><th>시간</th><th>이벤트</th><th>메모</th></tr>
</thead>
<tbody>
{''.join(event_rows) if event_rows else '<tr><td colspan="5">기록된 이벤트 없음</td></tr>'}
</tbody>
</table>

<h2>4. 판독/보고서</h2>
<div class="note">{note if note else '작성된 판독/보고서 없음'}</div>

<h2>5. 캡처 이미지</h2>
{''.join(capture_blocks) if capture_blocks else '<p>저장된 캡처 없음</p>'}

<p class="small">
본 리포트는 블랙박스 영상의 프레임 단위 검토를 보조하기 위한 자료입니다.
최종 감정에서는 원본성, FPS, 프레임 누락, 렌즈왜곡, 현장거리 확인이 함께 검토되어야 합니다.
</p>
</body>
</html>
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        with open(self.output_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if self.speed_results:
            self.write_speed_csv(self.output_dir / "speed_results.csv")

        QMessageBox.information(self, "완료", f"HTML 리포트 생성 완료\n{report_path}")
        self.statusBar().showMessage(f"HTML 리포트 생성: {report_path}")


    def closeEvent(self, event):
        if self.lane_count_worker is not None:
            self.lane_count_worker.cancel()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = BlackboxSpeedViewer()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
