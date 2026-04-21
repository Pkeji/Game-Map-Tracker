"""引擎层接口：任何跟点算法都实现 BaseTracker.step()，统一返回 TrackResult。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class TrackState(Enum):
    LOCKED = "locked"          # 精确锁定（红点）
    INERTIAL = "inertial"      # 短暂丢失用上一帧兜底（黄点）
    LOST = "lost"              # 彻底跟丢，需要手动定位（灰）
    SEARCHING = "searching"    # 引擎还没出结果或初始化中


@dataclass
class TrackResult:
    state: TrackState
    x: Optional[int] = None
    y: Optional[int] = None
    match_count: int = 0
    latency_ms: float = 0.0     # 本帧推理耗时


class BaseTracker:
    """所有跟点器必须实现 step(minimap_bgr) -> TrackResult。"""

    map_width: int
    map_height: int
    logic_map_bgr: np.ndarray
    display_map_bgr: np.ndarray

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        raise NotImplementedError

    def set_anchor(self, x: int, y: int) -> None:
        """手动重定位：由 UI 在丢失时调用。"""
        raise NotImplementedError
