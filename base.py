"""Tracker interfaces consumed by the island UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class TrackState(Enum):
    LOCKED = "locked"
    INERTIAL = "inertial"
    LOST = "lost"
    SEARCHING = "searching"


@dataclass
class TrackResult:
    state: TrackState
    x: Optional[int] = None
    y: Optional[int] = None
    match_count: int = 0
    latency_ms: float = 0.0


class BaseTracker:
    """Common tracker protocol consumed by the island UI."""

    map_width: int
    map_height: int
    logic_map_bgr: np.ndarray

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        raise NotImplementedError

    def set_anchor(self, x: int, y: int) -> None:
        raise NotImplementedError
