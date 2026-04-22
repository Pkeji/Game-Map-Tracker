"""SIFT + FLANN + RANSAC 跟点引擎。

从 main_sift.py 抽取，去掉了 Tk 耦合。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

import config
from .base import BaseTracker, TrackResult, TrackState


class SiftTracker(BaseTracker):
    def __init__(self) -> None:
        self.logic_map_bgr = cv2.imread(config.LOGIC_MAP_PATH)
        if self.logic_map_bgr is None:
            raise FileNotFoundError(f"找不到逻辑地图：{config.LOGIC_MAP_PATH}")
        self.display_map_bgr = cv2.imread(config.DISPLAY_MAP_PATH)
        if self.display_map_bgr is None:
            raise FileNotFoundError(f"找不到显示地图：{config.DISPLAY_MAP_PATH}")

        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]
        dh, dw = self.display_map_bgr.shape[:2]
        if (dh, dw) != (self.map_height, self.map_width):
            raise ValueError(
                f"逻辑图({self.map_width}x{self.map_height}) 与 "
                f"显示图({dw}x{dh}) 尺寸不一致"
            )

        self.clahe = cv2.createCLAHE(clipLimit=config.SIFT_CLAHE_LIMIT, tileGridSize=(8, 8))
        logic_gray = cv2.cvtColor(self.logic_map_bgr, cv2.COLOR_BGR2GRAY)
        logic_gray = self.clahe.apply(logic_gray)

        self.sift = cv2.SIFT_create()
        self.kp_big, self.des_big = self.sift.detectAndCompute(logic_gray, None)
        self._kp_big_pts = np.array([kp.pt for kp in self.kp_big], dtype=np.float32)

        FLANN_INDEX_KDTREE = 1
        self.flann = cv2.FlannBasedMatcher(
            dict(algorithm=FLANN_INDEX_KDTREE, trees=5),
            dict(checks=50),
        )
        self.bf = cv2.BFMatcher(cv2.NORM_L2)

        self._local_radius = float(getattr(config, "SIFT_LOCAL_SEARCH_RADIUS", 400) or 400)
        self._last_x: int | None = None
        self._last_y: int | None = None
        self._lost_frames = 0
        self._max_lost = config.MAX_LOST_FRAMES

    def set_anchor(self, x: int, y: int) -> None:
        self._last_x, self._last_y = int(x), int(y)
        self._lost_frames = 0

    def _match(self, des_mini: np.ndarray) -> tuple[list, np.ndarray]:
        """优先在上次坐标附近做 BFMatcher 局部搜索，命中不足或没锚点时退回全图 FLANN。

        返回 (good_matches, train_idx_map)：m.trainIdx 是子集下标，
        train_idx_map[m.trainIdx] 映射回 self.kp_big 全局下标。
        """
        ratio = config.SIFT_MATCH_RATIO
        local_threshold = max(config.SIFT_MIN_MATCH_COUNT + 3, 8)

        if (
            self._last_x is not None
            and self._last_y is not None
            and self._kp_big_pts.size > 0
        ):
            dx = self._kp_big_pts[:, 0] - self._last_x
            dy = self._kp_big_pts[:, 1] - self._last_y
            mask = (dx * dx + dy * dy) <= (self._local_radius * self._local_radius)
            local_idx = np.nonzero(mask)[0]
            if local_idx.size >= config.SIFT_MIN_MATCH_COUNT * 2:
                des_local = self.des_big[local_idx]
                matches = self.bf.knnMatch(des_mini, des_local, k=2)
                good = [
                    m for pair in matches if len(pair) == 2
                    for m, n in [pair]
                    if m.distance < ratio * n.distance
                ]
                if len(good) >= local_threshold:
                    return good, local_idx

        matches = self.flann.knnMatch(des_mini, self.des_big, k=2)
        good = [
            m for pair in matches if len(pair) == 2
            for m, n in [pair]
            if m.distance < ratio * n.distance
        ]
        identity = np.arange(len(self.kp_big), dtype=np.int64)
        return good, identity

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        t0 = time.time()
        gray = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
        gray = self.clahe.apply(gray)

        kp_mini, des_mini = self.sift.detectAndCompute(gray, None)
        locked = False
        cx = cy = None
        good_count = 0

        if des_mini is not None and len(kp_mini) >= 2:
            good, train_idx_map = self._match(des_mini)
            good_count = len(good)

            if good_count >= config.SIFT_MIN_MATCH_COUNT:
                src = np.float32([kp_mini[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                dst = np.float32(
                    [self.kp_big[train_idx_map[m.trainIdx]].pt for m in good]
                ).reshape(-1, 1, 2)
                M, _ = cv2.findHomography(src, dst, cv2.RANSAC, config.SIFT_RANSAC_THRESHOLD)
                if M is not None:
                    h, w = gray.shape
                    center = cv2.perspectiveTransform(
                        np.float32([[[w / 2, h / 2]]]), M
                    )
                    tx, ty = int(center[0][0][0]), int(center[0][0][1])
                    if 0 <= tx < self.map_width and 0 <= ty < self.map_height:
                        locked = True
                        cx, cy = tx, ty
                        self._last_x, self._last_y = tx, ty
                        self._lost_frames = 0

        latency = (time.time() - t0) * 1000.0

        if locked:
            return TrackResult(TrackState.LOCKED, cx, cy, good_count, latency)

        if self._last_x is not None and self._lost_frames < self._max_lost:
            self._lost_frames += 1
            return TrackResult(
                TrackState.INERTIAL, self._last_x, self._last_y, good_count, latency
            )

        # 真正跟丢后清空旧锚点。传送前打开大地图等 UI 变化可能让旧锚点失真，
        # 后续帧应直接回到全图重搜，而不是继续被旧位置拖住。
        self._last_x = None
        self._last_y = None
        return TrackResult(TrackState.LOST, latency_ms=latency)
