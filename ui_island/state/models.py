"""Dataclass state containers for island window subsystems."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QCheckBox, QFrame, QLineEdit, QPushButton

from base import TrackResult, TrackState


@dataclass
class WindowModeState:
    mode_before_max: object | None = None
    applying_mode: bool = False
    preferred_right_edge: int | None = None


@dataclass
class WindowLayoutPrefs:
    sidebar_collapsed: bool = False
    sidebar_width: int = 320
    paused_sidebar_width: int = 320
    normal_minimum_width: int = 0
    normal_minimum_height: int = 0
    compact_minimum_height: int = 0
    sidebar_collapsed_before_pause: bool | None = None
    sidebar_width_before_pause: int | None = None
    sidebar_collapsed_before_max: bool | None = None
    sidebar_width_before_max: int | None = None
    sidebar_expand_restore_geometry: QRect | None = None
    geometry_before_max: QRect | None = None
    size_prefs: dict[object, tuple[int, int]] = field(default_factory=dict)


@dataclass
class RoutePanelState:
    recent_route_names: list[str] = field(default_factory=list)
    route_checkboxes: dict[str, list[QCheckBox]] = field(default_factory=dict)
    route_widgets_by_category: dict[str, list[tuple[str, object]]] = field(default_factory=dict)
    route_sections: dict[str, object] = field(default_factory=dict)
    active_route_rename_item: object | None = None
    adding_category: bool = False
    add_category_row: QFrame | None = None
    add_category_input: QLineEdit | None = None
    add_category_confirm_btn: QPushButton | None = None
    add_category_cancel_btn: QPushButton | None = None
    search_term: str = ""


@dataclass
class TrackingState:
    locked: bool = False
    running: bool = True
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=30))
    last_result: TrackResult | None = None
    last_player_xy: tuple[int, int] | None = None
    latest_minimap: np.ndarray | None = None
    tracking_attempts_paused: bool = False
    tracking_paused_state: TrackState = TrackState.SEARCHING
    jump_anomaly_count: int = 0
    preferred_locked: bool = False
    lock_state_before_lost: bool | None = None
    restore_lock_after_relocate: bool | None = None
    tracking_bootstrap_pending: bool = False


@dataclass
class HotkeyState:
    listener: object | None = None
    thread: object | None = None
    thread_id: int | None = None
    last_hotkey_at: float = 0.0
    alt_pressed: bool = False
