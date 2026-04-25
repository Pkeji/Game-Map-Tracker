"""LoFTR 跟点引擎。

从 main_ai.py 抽取。针对"瞬移拒收"问题：
当连续 N 帧落在 dist>=TELEPORT_THRESHOLD 的位置仍稳定时，强制接受新坐标。
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import torch

import config
from .tracker_engine import LoftrEngine
from base import BaseTracker, TrackResult, TrackState
from map_image_loader import load_map_image


TELEPORT_THRESHOLD = 500      # 超过此距离视为瞬移候选
TELEPORT_CONFIRM_FRAMES = 3   # 连续 N 帧都指向同一远点 -> 接受


class AiTracker(BaseTracker):
    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.engine = LoftrEngine(self.device)

        self.logic_map_bgr = load_map_image(config.LOGIC_MAP_PATH, label="AI logic map")
        if self.logic_map_bgr is None:
            raise FileNotFoundError(f"找不到逻辑地图：{config.LOGIC_MAP_PATH}")
        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]

        self._last_x = self.map_width // 2
        self._last_y = self.map_height // 2
        self._smoothed_x: float | None = None
        self._smoothed_y: float | None = None
        self._search_radius = config.AI_TRACK_RADIUS
        self._base_radius = config.AI_TRACK_RADIUS
        self._lost_frames = 0
        self._max_lost = 4

        # 瞬移候选缓冲
        self._teleport_cand: tuple[int, int] | None = None
        self._teleport_streak = 0

    def set_anchor(self, x: int, y: int) -> None:
        self._last_x, self._last_y = int(x), int(y)
        self._smoothed_x, self._smoothed_y = float(x), float(y)
        self._lost_frames = 0
        self._search_radius = self._base_radius + 200
        self._teleport_cand = None
        self._teleport_streak = 0

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        t0 = time.time()

        x1 = max(0, self._last_x - self._search_radius)
        y1 = max(0, self._last_y - self._search_radius)
        x2 = min(self.map_width, self._last_x + self._search_radius)
        y2 = min(self.map_height, self._last_y + self._search_radius)
        local = self.logic_map_bgr[y1:y2, x1:x2]

        found = False
        match_count = 0

        if local.shape[0] >= 16 and local.shape[1] >= 16:
            t_mini = self.engine.preprocess(minimap_bgr)
            t_local = self.engine.preprocess(local)
            corr = self.engine.match(t_mini, t_local)
            mk0 = corr["keypoints0"].cpu().numpy()
            mk1 = corr["keypoints1"].cpu().numpy()
            conf = corr["confidence"].cpu().numpy()

            mask = conf > config.AI_CONFIDENCE_THRESHOLD
            mk0, mk1 = mk0[mask], mk1[mask]
            match_count = len(mk0)

            if match_count >= config.AI_MIN_MATCH_COUNT:
                M, _ = cv2.findHomography(mk0, mk1, cv2.RANSAC, config.AI_RANSAC_THRESHOLD)
                if M is not None:
                    h, w = minimap_bgr.shape[:2]
                    c = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), M)
                    rx = float(c[0][0][0]) + x1
                    ry = float(c[0][0][1]) + y1
                    if 0 <= rx < self.map_width and 0 <= ry < self.map_height:
                        found = self._accept(rx, ry)

        latency = (time.time() - t0) * 1000.0

        if found:
            self._last_x = int(self._smoothed_x)
            self._last_y = int(self._smoothed_y)
            self._lost_frames = 0
            self._search_radius = self._base_radius
            return TrackResult(
                TrackState.LOCKED, self._last_x, self._last_y, match_count, latency
            )

        self._lost_frames += 1
        if self._lost_frames == 1:
            self._search_radius += 300

        if self._lost_frames <= self._max_lost:
            return TrackResult(
                TrackState.INERTIAL, self._last_x, self._last_y, match_count, latency
            )

        return TrackResult(TrackState.LOST, latency_ms=latency)

    def _accept(self, rx: float, ry: float) -> bool:
        """返回本帧是否产生了有效坐标（并更新平滑）。"""
        if self._smoothed_x is None:
            self._smoothed_x, self._smoothed_y = rx, ry
            return True

        dist = np.hypot(rx - self._smoothed_x, ry - self._smoothed_y)

        if dist < TELEPORT_THRESHOLD:
            alpha = 0.15 if dist < 15 else 0.45
            self._smoothed_x = alpha * rx + (1 - alpha) * self._smoothed_x
            self._smoothed_y = alpha * ry + (1 - alpha) * self._smoothed_y
            self._teleport_cand = None
            self._teleport_streak = 0
            return True

        # 远跳：连续几帧都在同一远点才接受（避免单帧误匹配）
        if self._teleport_cand is None:
            self._teleport_cand = (int(rx), int(ry))
            self._teleport_streak = 1
            return False

        cand_x, cand_y = self._teleport_cand
        if np.hypot(rx - cand_x, ry - cand_y) < 80:
            self._teleport_streak += 1
            if self._teleport_streak >= TELEPORT_CONFIRM_FRAMES:
                self._smoothed_x, self._smoothed_y = rx, ry
                self._teleport_cand = None
                self._teleport_streak = 0
                return True
        else:
            self._teleport_cand = (int(rx), int(ry))
            self._teleport_streak = 1
        return False
