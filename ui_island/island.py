"""Top-of-screen island overlay with interactive map and route tools."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque

import mss
import numpy as np

try:
    from pynput import keyboard
except ImportError:  # pragma: no cover
    keyboard = None

from enum import Enum

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import config
from engines import BaseTracker, TrackResult, TrackState
from route_manager import RouteManager

from . import theme
from .map_view import MapView
from .win_overlay import apply_overlay_flags, set_click_through


class WindowMode(Enum):
    """主窗口的五种互斥形态。

    - PAUSED：手动停止导航（启动默认态），固定 EXPANDED_W × EXPANDED_H。
    - TRACKING_STABLE：定位稳定（跟踪器返回 LOCKED），用户可 resize，尺寸持久化。
    - TRACKING_INERTIAL：短暂失锁但仍有位置（跟踪器返回 INERTIAL），复用 STABLE 尺寸。
    - TRACKING_LOST：目标丢失 / 搜索中（LOST / SEARCHING），紧缩告警形态。
    - MAXIMIZED：铺满屏幕，独立形态；退出时回到进入前的 mode。
    """

    PAUSED = "paused"
    TRACKING_STABLE = "tracking_stable"
    TRACKING_INERTIAL = "tracking_inertial"
    TRACKING_LOST = "tracking_lost"
    MAXIMIZED = "maximized"


_TRACKING_MODES = {
    WindowMode.TRACKING_STABLE,
    WindowMode.TRACKING_INERTIAL,
    WindowMode.TRACKING_LOST,
}
_STABLE_FAMILY = {WindowMode.TRACKING_STABLE, WindowMode.TRACKING_INERTIAL}


def _tracker_state_to_mode(state: TrackState) -> WindowMode:
    if state == TrackState.LOCKED:
        return WindowMode.TRACKING_STABLE
    if state == TrackState.INERTIAL:
        return WindowMode.TRACKING_INERTIAL
    # LOST / SEARCHING 都归紧缩告警态
    return WindowMode.TRACKING_LOST


class _StatusDot(QWidget):
    COLORS = {
        TrackState.LOCKED: theme.DOT_LOCKED,
        TrackState.INERTIAL: theme.DOT_INERTIAL,
        TrackState.LOST: theme.DOT_LOST,
        TrackState.SEARCHING: theme.DOT_SEARCHING,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = theme.DOT_SEARCHING
        self.setFixedSize(10, 10)

    def set_state(self, state: TrackState) -> None:
        new_color = self.COLORS.get(state, theme.DOT_SEARCHING)
        if new_color != self._color:
            self._color = new_color
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self._color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())


class _RouteSection(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._force_open = False
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setText(title)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.toggled.connect(self.set_expanded)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("RouteSectionBody")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 0, 4)
        self.body_layout.setSpacing(4)
        self.body_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)
        layout.addWidget(self.body)
        self._sync_state()

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._sync_state()

    def set_force_open(self, force_open: bool) -> None:
        self._force_open = force_open
        self._sync_state()

    def _sync_state(self) -> None:
        visible = self._expanded or self._force_open
        self.body.setVisible(visible)
        self.header.blockSignals(True)
        self.header.setChecked(self._expanded)
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)


class IslandWindow(QWidget):
    _frame_ready = Signal(object)
    _toggle_lock_requested = Signal()

    _NATIVE_HOTKEY_ID_ALT_GRAVE = 1
    _HOTKEY_DEBOUNCE_SEC = 0.35
    _AUTO_RECENTER_MOVE_THRESHOLD = 3
    _RESIZE_MARGIN = 6
    _SIDEBAR_RESIZE_MARGIN = 6
    _SIDEBAR_MIN_WIDTH = 200
    _HEADER_ICON_SWITCH_WIDTH = 600

    def __init__(self, tracker: BaseTracker, route_mgr: RouteManager) -> None:
        super().__init__(None)
        theme.ensure_tooltip_style()
        self.tracker = tracker
        self.route_mgr = route_mgr

        self._locked = False
        self._running = True
        self._latencies: deque[float] = deque(maxlen=30)
        self._last_result: TrackResult | None = None
        self._last_player_xy: tuple[int, int] | None = None
        self._latest_minimap: np.ndarray | None = None

        self._is_windows = sys.platform.startswith("win")
        self._window_margin = 0 if self._is_windows else 10
        self._shadow_enabled = not self._is_windows

        self._hotkey_listener = None
        self._hotkey_thread = None
        self._hotkey_thread_id = None
        self._last_hotkey_at = 0.0
        self._alt_pressed = False

        self._recent_limit = max(0, int(getattr(config, "ROUTE_RECENT_LIMIT", 5) or 0))
        self._recent_route_names = self._load_recent_routes()
        self._route_checkboxes: dict[str, list[QCheckBox]] = {}
        self._route_widgets_by_category: dict[str, list[tuple[str, QCheckBox]]] = {}
        self._route_sections: dict[str, _RouteSection] = {}

        # 侧边栏折叠状态和宽度：优先读 config，没有则走默认
        saved_collapsed = config.SIDEBAR_COLLAPSED
        saved_sidebar_w = config.SIDEBAR_WIDTH
        self._sidebar_collapsed = bool(saved_collapsed) if saved_collapsed is not None else False
        try:
            tracking_sidebar_width = max(120, int(saved_sidebar_w)) if saved_sidebar_w is not None else 320
        except (TypeError, ValueError):
            tracking_sidebar_width = 320
        saved_paused_sidebar_w = getattr(config, "PAUSED_SIDEBAR_WIDTH", None)
        try:
            self._paused_sidebar_width = (
                max(120, int(saved_paused_sidebar_w))
                if saved_paused_sidebar_w is not None
                else tracking_sidebar_width
            )
        except (TypeError, ValueError):
            self._paused_sidebar_width = tracking_sidebar_width
        self._sidebar_width = self._paused_sidebar_width

        self._normal_minimum_width = theme.WINDOW_MIN_W + self._window_margin * 2
        self._normal_minimum_height = max(
            theme.WINDOW_MIN_H,
            theme.TRACKING_WINDOW_MIN_H,
        ) + self._window_margin * 2
        self._tracking_attempts_paused = False
        self._tracking_paused_state = TrackState.SEARCHING
        self._jump_anomaly_count = 0
        self._preferred_locked = False
        self._lock_state_before_lost: bool | None = None
        self._restore_lock_after_relocate: bool | None = None

        # ---- 状态机：window mode + 各模式的尺寸偏好 ----
        self._mode = WindowMode.PAUSED                      # 启动默认暂停态
        self._mode_before_max: WindowMode | None = None     # 最大化前的 mode
        self._geometry_before_max: QRect | None = None
        self._applying_mode = False                         # _enter_mode 内部保护
        self._preferred_right_edge: int | None = None       # 锚点：窗口右边缘
        # 进 PAUSED 前的侧边栏状态。预填为"config 读到的用户偏好"，
        # 启动后走 _enter_mode(PAUSED) 强制展开但会把这个备份保留下来——
        # 下次离开 PAUSED（比如点开始导航）时恢复用户偏好。
        self._sidebar_collapsed_before_pause: bool | None = bool(self._sidebar_collapsed)
        self._sidebar_width_before_pause: int | None = tracking_sidebar_width
        self._sidebar_collapsed_before_max: bool | None = None    # 进 MAXIMIZED 前的折叠状态
        self._sidebar_width_before_max: int | None = None         # 进 MAXIMIZED 前的宽度
        # 各模式的目标尺寸 (width, height)
        self._sidebar_expand_restore_geometry: QRect | None = None
        paused_w = theme.EXPANDED_W + self._window_margin * 2
        paused_h = theme.EXPANDED_H + self._window_margin * 2
        self._size_prefs: dict[WindowMode, tuple[int, int]] = {
            WindowMode.PAUSED: (paused_w, paused_h),
        }
        # 读取持久化的稳定态尺寸（若有）
        saved_stable = config.LOCKED_VIEW_SIZE
        if isinstance(saved_stable, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_stable["width"]))
                h = max(self._normal_minimum_height, int(saved_stable["height"]))
                self._size_prefs[WindowMode.TRACKING_STABLE] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass
        # 读取持久化的暂停态尺寸（若有）
        saved_paused = getattr(config, "PAUSED_VIEW_SIZE", None)
        if isinstance(saved_paused, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_paused["width"]))
                h = max(self._normal_minimum_height, int(saved_paused["height"]))
                self._size_prefs[WindowMode.PAUSED] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass
        # 防抖：稳定态 resize 结束 300ms 后写回 config
        self._stable_size_save_timer = QTimer(self)
        self._stable_size_save_timer.setSingleShot(True)
        self._stable_size_save_timer.setInterval(300)
        self._stable_size_save_timer.timeout.connect(self._flush_stable_size_to_config)
        # 防抖：暂停态尺寸同样持久化
        self._paused_size_save_timer = QTimer(self)
        self._paused_size_save_timer.setSingleShot(True)
        self._paused_size_save_timer.setInterval(300)
        self._paused_size_save_timer.timeout.connect(self._flush_paused_size_to_config)

        self._move_dragging = False
        self._move_drag_offset = None
        self._edge_cursor_active = False
        self._sidebar_resizing = False
        self._sidebar_resize_start_x = 0
        self._sidebar_resize_start_width = self._sidebar_width
        self._header_buttons_icon_only = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)

        self._build_ui()
        self._sync_normal_minimum_height()
        self._sync_compact_minimum_height()
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)
        self._install_resize_filters(self.root)
        self.installEventFilter(self)
        self._restore_or_center()
        # 启动时进入 PAUSED：强制展开侧边栏 + 设 UI 反馈 + 跟踪循环暂停
        self._enter_mode(WindowMode.PAUSED)
        # PAUSED 下默认渲染一次地图（居中），避免左侧全黑。
        # 用 QTimer.singleShot(0) 延到首次 layout 完成后执行，
        # 保证 map_view 的真实尺寸已经算好，zoom 才能算出合适值把地图填满。
        QTimer.singleShot(0, self._paint_default_map)

        self._toggle_lock_requested.connect(self.toggle_lock, Qt.QueuedConnection)
        self._frame_ready.connect(self._on_frame)

        self._minimap_region = config.MINIMAP
        self._start_hotkey_listener()

        self._thread = threading.Thread(target=self._tracker_loop, daemon=True)
        self._thread.start()

    def _build_ui(self) -> None:
        self.root = QFrame(self)
        self.root.setObjectName("IslandRoot")
        self.root.setStyleSheet(theme.ISLAND_QSS)

        if self._shadow_enabled:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(30)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 180))
            self.root.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._window_margin,
            self._window_margin,
            self._window_margin,
            self._window_margin,
        )
        outer.addWidget(self.root)

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(12, 8, 12, 10)
        root_layout.setSpacing(8)

        self._build_header(root_layout)
        self._build_body(root_layout)

    def _build_header(self, root_layout: QVBoxLayout) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.title_drag_area = QWidget()
        title_layout = QHBoxLayout(self.title_drag_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(10)

        self.dot = _StatusDot(self.title_drag_area)
        self.dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self.dot)

        self.coord_label = QLabel("-- , --", self.title_drag_area)
        self.coord_label.setObjectName("CoordLabel")
        self.coord_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self.coord_label)

        self.state_hint_label = QLabel("定位稳定")
        self.state_hint_label.setObjectName("StateHint")
        self.state_hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self.state_hint_label)

        self.unlock_hint_label = QLabel("快捷键Alt+~解锁")
        self.unlock_hint_label.setObjectName("MapHint")
        self.unlock_hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.unlock_hint_label.hide()
        title_layout.addWidget(self.unlock_hint_label)

        title_layout.addStretch()

        self.stat_label = QLabel("--- ms", self.title_drag_area)
        self.stat_label.setObjectName("StatLabel")
        self.stat_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_layout.addWidget(self.stat_label)

        self.title_drag_area.installEventFilter(self)
        header.addWidget(self.title_drag_area, stretch=1)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("WindowControl")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)

        self.min_btn = QPushButton("-")
        self.min_btn.setObjectName("WindowControl")
        self.min_btn.setToolTip("最小化")
        self.min_btn.setFont(self._window_control_font(18))
        self.min_btn.clicked.connect(self._collapse_to_icon)
        header.addWidget(self.min_btn)

        self.max_btn = QPushButton("▢")
        self.max_btn.setObjectName("WindowControl")
        self.max_btn.setToolTip("最大化")
        self.max_btn.setFont(self._window_control_font(18))
        self.max_btn.clicked.connect(self._toggle_maximize_restore)
        header.addWidget(self.max_btn)

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WindowControl")
        self.close_btn.setToolTip("关闭")
        self.close_btn.setFont(self._window_control_font(18))
        self.close_btn.clicked.connect(self.close)
        header.addWidget(self.close_btn)

        self.relocate_btn = QPushButton("重定位")
        self.relocate_btn.setObjectName("HeaderActionButton")
        self.relocate_btn.setProperty("iconRole", "locate")
        self.relocate_btn.setToolTip("重定位")
        self.relocate_btn.clicked.connect(self._prompt_relocate)
        header.addWidget(self.relocate_btn)

        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.setObjectName("HeaderActionButton")
        self.reset_view_btn.setProperty("iconRole", "reset")
        self.reset_view_btn.setToolTip("重置视图")
        self.reset_view_btn.clicked.connect(self._reset_map_view)
        header.addWidget(self.reset_view_btn)
        header.removeWidget(self.reset_view_btn)
        header.insertWidget(header.indexOf(self.relocate_btn), self.reset_view_btn)

        self.sidebar_toggle_btn = QPushButton("隐藏侧边栏")
        self.sidebar_toggle_btn.setObjectName("TopSidebarToggle")
        self.sidebar_toggle_btn.setProperty("iconRole", "sidebar")
        self.sidebar_toggle_btn.setToolTip("隐藏侧边栏")
        self.sidebar_toggle_btn.clicked.connect(self._handle_sidebar_action)
        header.addWidget(self.sidebar_toggle_btn)

        self.terminate_nav_btn = QPushButton("终止导航")
        self.terminate_nav_btn.setObjectName("HeaderActionButton")
        self.terminate_nav_btn.setProperty("iconRole", "terminate")
        self.terminate_nav_btn.setToolTip("终止导航")
        self.terminate_nav_btn.clicked.connect(self._pause_navigation)
        header.addWidget(self.terminate_nav_btn)

        self.lock_btn = QPushButton("锁定")
        self.lock_btn.setObjectName("HeaderActionButton")
        self.lock_btn.setProperty("iconRole", "lock")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setToolTip("锁定")
        self.lock_btn.clicked.connect(self.toggle_lock)
        header.addWidget(self.lock_btn)

        self._update_header_button_labels()
        root_layout.addLayout(header)

    @staticmethod
    def _window_control_font(size: int) -> QFont:
        font = QFont()
        font.setPointSize(size)
        font.setBold(True)
        return font

    def _build_body(self, root_layout: QVBoxLayout) -> None:
        self.alert_card = QFrame()
        self.alert_card.setObjectName("AlertCard")
        self.alert_card.hide()
        alert_layout = QHBoxLayout(self.alert_card)
        alert_layout.setContentsMargins(18, 16, 18, 16)
        alert_layout.setSpacing(12)
        alert_layout.addStretch()

        self.alert_message = QLabel("目标丢失，正在尝试重新定位。")
        self.alert_message.setObjectName("AlertMessage")
        self.alert_message.setAlignment(Qt.AlignCenter)
        self.alert_message.setWordWrap(True)
        alert_layout.addWidget(self.alert_message)

        self.alert_terminate_btn = QPushButton("终止导航")
        self.alert_terminate_btn.setObjectName("AlertAction")
        self.alert_terminate_btn.clicked.connect(self._pause_navigation)
        alert_layout.addWidget(self.alert_terminate_btn)
        alert_layout.addStretch()
        root_layout.addWidget(self.alert_card)

        self.body_container = QWidget()
        body = QHBoxLayout(self.body_container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)

        self.map_shell = QWidget()
        map_layout = QVBoxLayout(self.map_shell)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(10)

        self.map_view = MapView(self.route_mgr)
        self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.map_view.set_maps(self.tracker.display_map_bgr)
        self.map_view.relocate_requested.connect(self._on_relocate)
        self.map_view.manual_view_changed.connect(self._handle_manual_map_navigation)
        map_layout.addWidget(self.map_view, stretch=1)

        self.tracked_routes_card = QFrame()
        self.tracked_routes_card.setObjectName("PanelCard")
        self.tracked_routes_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.tracked_routes_layout = QVBoxLayout(self.tracked_routes_card)
        self.tracked_routes_layout.setContentsMargins(12, 0, 12, 0)
        self.tracked_routes_layout.setSpacing(4)

        self.tracked_routes_title = QLabel("当前追踪路线")
        self.tracked_routes_title.setObjectName("TitleLabel")
        self.tracked_routes_layout.addWidget(self.tracked_routes_title)

        self.tracked_routes_scroll = QScrollArea()
        self.tracked_routes_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.tracked_routes_scroll.setWidgetResizable(True)
        self.tracked_routes_scroll.setFrameShape(QFrame.NoFrame)
        self.tracked_routes_scroll.viewport().setAutoFillBackground(False)
        self.tracked_routes_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tracked_routes_scroll.setMaximumHeight(theme.TRACKED_ROUTES_MAX_HEIGHT)

        self.tracked_routes_inner = QWidget()
        self.tracked_routes_grid = QGridLayout(self.tracked_routes_inner)
        self.tracked_routes_grid.setContentsMargins(0, 0, 0, 0)
        self.tracked_routes_grid.setHorizontalSpacing(16)
        self.tracked_routes_grid.setVerticalSpacing(6)
        self.tracked_routes_grid.setColumnStretch(0, 1)
        self.tracked_routes_grid.setColumnStretch(1, 1)

        self.tracked_routes_scroll.setWidget(self.tracked_routes_inner)
        self.tracked_routes_layout.addWidget(self.tracked_routes_scroll)
        map_layout.addWidget(self.tracked_routes_card)
        map_layout.setStretch(0, 1)
        map_layout.setStretch(1, 0)

        body.addWidget(self.map_shell, stretch=7)

        self.sidebar_shell = QWidget()
        shell_layout = QVBoxLayout(self.sidebar_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.NoFrame)
        self.side_scroll.viewport().setAutoFillBackground(False)
        self.side_scroll.setMinimumWidth(200)

        self.side_panel = QFrame()
        self.side_panel.setObjectName("PanelCard")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(10)
        side_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)

        map_hint = QLabel("滚轮缩放，左键拖动，双击选点")
        map_hint.setObjectName("MapHint")
        side_layout.addWidget(map_hint)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索路线...")
        self.search_input.textChanged.connect(self._apply_route_filter)
        side_layout.addWidget(self.search_input)

        recent_title = QLabel("最近常用")
        recent_title.setObjectName("TitleLabel")
        side_layout.addWidget(recent_title)

        self.recent_card = QFrame()
        self.recent_card.setObjectName("PanelCard")
        recent_card_layout = QVBoxLayout(self.recent_card)
        recent_card_layout.setContentsMargins(10, 10, 10, 10)
        recent_card_layout.setSpacing(4)

        self.recent_scroll = QScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFrameShape(QFrame.NoFrame)
        self.recent_scroll.viewport().setAutoFillBackground(False)
        self.recent_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recent_scroll.setMaximumHeight(theme.RECENT_ROUTES_MAX_HEIGHT)

        self.recent_scroll_inner = QWidget()
        self.recent_scroll_inner.setAttribute(Qt.WA_StyledBackground, True)
        self.recent_routes_layout = QVBoxLayout(self.recent_scroll_inner)
        self.recent_routes_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_routes_layout.setSpacing(4)
        self.recent_routes_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)
        self.recent_scroll.setWidget(self.recent_scroll_inner)
        recent_card_layout.addWidget(self.recent_scroll)
        side_layout.addWidget(self.recent_card)

        routes_title = QLabel("路线列表")
        routes_title.setObjectName("TitleLabel")
        side_layout.addWidget(routes_title)

        self.routes_scroll = QScrollArea()
        self.routes_scroll.setWidgetResizable(True)
        self.routes_scroll.setFrameShape(QFrame.NoFrame)
        self.routes_scroll.viewport().setAutoFillBackground(False)
        self.routes_scroll.setMinimumHeight(theme.ROUTES_LIST_MIN_HEIGHT)

        routes_scroll_inner = QWidget()
        routes_scroll_inner.setObjectName("RoutesScrollInner")
        routes_scroll_inner.setAttribute(Qt.WA_StyledBackground, True)
        self.routes_layout = QVBoxLayout(routes_scroll_inner)
        self.routes_layout.setContentsMargins(0, 0, 0, 0)
        self.routes_layout.setSpacing(8)
        self._build_route_sections()
        self.routes_layout.addStretch()
        self.routes_scroll.setWidget(routes_scroll_inner)
        side_layout.addWidget(self.routes_scroll, stretch=1)

        self.side_scroll.setWidget(self.side_panel)
        shell_layout.addWidget(self.side_scroll, stretch=1)

        body.addWidget(self.sidebar_shell, stretch=4)
        root_layout.addWidget(self.body_container, stretch=1)

        self.map_view.set_center_locked(True)
        self._refresh_tracked_routes()
        self._apply_sidebar_state()
        self._refresh_recent_routes()
        self._apply_route_filter()
        self._update_window_controls()

    def _build_route_sections(self) -> None:
        for category in self.route_mgr.categories:
            section = _RouteSection(category)
            self._route_sections[category] = section
            self._route_widgets_by_category[category] = []

            routes = sorted(
                self.route_mgr.route_groups[category],
                key=lambda route: route.get("display_name", ""),
            )
            for route in routes:
                name = route.get("display_name", "")
                checkbox = self._create_route_checkbox(name)
                section.add_widget(checkbox)
                self._route_widgets_by_category[category].append((name, checkbox))

            self.routes_layout.addWidget(section)

    def _create_route_checkbox(self, name: str) -> QCheckBox:
        checkbox = QCheckBox(name)
        checkbox.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
        checkbox.setChecked(self.route_mgr.visibility.get(name, False))
        checkbox.toggled.connect(
            lambda enabled, route_name=name, source=checkbox: self._toggle_route(route_name, enabled, source)
        )
        self._route_checkboxes.setdefault(name, []).append(checkbox)
        return checkbox

    def _remove_recent_widgets(self) -> None:
        while self.recent_routes_layout.count():
            item = self.recent_routes_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                self._unregister_route_checkbox(widget.text(), widget)
            widget.deleteLater()

    def _remove_tracked_route_widgets(self) -> None:
        while self.tracked_routes_grid.count():
            item = self.tracked_routes_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                self._unregister_route_checkbox(widget.text(), widget)
            widget.deleteLater()

    def _refresh_recent_routes(self) -> None:
        self._remove_recent_widgets()

        search_term = self.search_input.text().strip().casefold()
        route_names = [name for name in self._recent_route_names if self._matches_route(name, search_term)]
        if self._recent_limit:
            route_names = route_names[: self._recent_limit]
        else:
            route_names = []

        if route_names:
            for name in route_names:
                self.recent_routes_layout.addWidget(self._create_route_checkbox(name))
        else:
            hint = QLabel("暂无最近常用路线")
            hint.setObjectName("EmptyHint")
            hint.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
            hint.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.recent_routes_layout.addWidget(hint)
        self.recent_routes_layout.addStretch()
        self.recent_scroll_inner.adjustSize()
        self._sync_recent_scroll_height(len(route_names) if route_names else 1)

    def _sync_recent_scroll_height(self, item_count: int) -> None:
        rows = max(1, item_count)
        spacing = self.recent_routes_layout.spacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.RECENT_ROUTES_MAX_HEIGHT, content_height)
        self.recent_scroll.setFixedHeight(target_height)
        card_height = target_height + theme.RECENT_ROUTE_CARD_PADDING
        self.recent_card.setMinimumHeight(card_height)
        self.recent_card.setMaximumHeight(card_height)

    def _unregister_route_checkbox(self, name: str, checkbox: QCheckBox) -> None:
        widgets = self._route_checkboxes.get(name)
        if not widgets:
            return
        if checkbox in widgets:
            widgets.remove(checkbox)
        if not widgets:
            self._route_checkboxes.pop(name, None)

    def _toggle_route(self, name: str, enabled: bool, source: QCheckBox) -> None:
        self.route_mgr.visibility[name] = enabled
        if enabled:
            self._remember_recent_route(name)
        self.route_mgr.save_visibility()
        self._sync_route_checkboxes(name, enabled, source)
        self._refresh_tracked_routes()
        self._refresh_recent_routes()

    def _sync_route_checkboxes(self, name: str, enabled: bool, source: QCheckBox) -> None:
        for checkbox in list(self._route_checkboxes.get(name, [])):
            if checkbox is source:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
            checkbox.blockSignals(False)

    def _remember_recent_route(self, name: str) -> None:
        if name in self._recent_route_names:
            self._recent_route_names.remove(name)
        self._recent_route_names.insert(0, name)
        self._save_recent_routes()

    def _refresh_tracked_routes(self) -> None:
        route_names = self.route_mgr.visible_route_names()
        self.tracked_routes_title.setText(f"当前追踪路线 ({len(route_names)})")
        self._remove_tracked_route_widgets()

        if route_names:
            for index, name in enumerate(route_names):
                checkbox = self._create_route_checkbox(name)
                row = index // 2
                column = index % 2
                self.tracked_routes_grid.addWidget(checkbox, row, column)
        else:
            empty_label = QLabel("暂未选择路线")
            empty_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            empty_label.setStyleSheet(f"font-size: 12px; color: {theme.FG_DIM};")
            self.tracked_routes_grid.addWidget(empty_label, 0, 0, 1, 2)

        self.tracked_routes_inner.adjustSize()
        self._sync_tracked_routes_height(len(route_names))
        self._schedule_layout_refresh()

    def _sync_tracked_routes_height(self, item_count: int) -> None:
        rows = max(1, (max(1, item_count) + 1) // 2)
        spacing = self.tracked_routes_grid.verticalSpacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.TRACKED_ROUTES_MAX_HEIGHT, content_height)
        self.tracked_routes_scroll.setFixedHeight(target_height)
        margins = self.tracked_routes_layout.contentsMargins()
        card_height = (
            margins.top()
            + self.tracked_routes_title.sizeHint().height()
            + self.tracked_routes_layout.spacing()
            + target_height
            + margins.bottom()
        )
        self.tracked_routes_card.setMinimumHeight(card_height)
        self.tracked_routes_card.setMaximumHeight(card_height)

    def _sync_normal_minimum_height(self) -> None:
        for layout in (
            self.root.layout(),
            self.body_container.layout(),
            self.map_shell.layout(),
            self.tracked_routes_layout,
        ):
            if layout is not None:
                layout.activate()

        root_layout = self.root.layout()
        if root_layout is None:
            return

        header_item = root_layout.itemAt(0)
        header_height = header_item.sizeHint().height() if header_item is not None else 0
        body_height = self.body_container.minimumSizeHint().height()
        margins = root_layout.contentsMargins()
        spacing = root_layout.spacing()
        computed_height = (
            self._window_margin * 2
            + margins.top()
            + margins.bottom()
            + header_height
            + body_height
            + spacing * 2
        )
        self._normal_minimum_height = max(self._normal_minimum_height, computed_height)

    def _sync_compact_minimum_height(self) -> None:
        root_layout = self.root.layout()
        if root_layout is None:
            return

        root_layout.activate()
        header_item = root_layout.itemAt(0)
        header_height = header_item.sizeHint().height() if header_item is not None else 0
        alert_height = self.alert_card.sizeHint().height()
        margins = root_layout.contentsMargins()
        spacing = root_layout.spacing()
        self._compact_minimum_height = max(
            theme.COMPACT_ALERT_HEIGHT + self._window_margin * 2,
            self._window_margin * 2
            + margins.top()
            + margins.bottom()
            + header_height
            + spacing
            + alert_height,
        )

    def _schedule_layout_refresh(self) -> None:
        QTimer.singleShot(0, self._refresh_layout_constraints)

    def _refresh_layout_constraints(self) -> None:
        self._sync_normal_minimum_height()
        self._sync_compact_minimum_height()
        self.setMinimumWidth(self._normal_minimum_width)

        if self._mode == WindowMode.TRACKING_LOST:
            self.setMinimumHeight(self._compact_minimum_height)
            return

        self.setMinimumHeight(self._normal_minimum_height)

        if self.isMaximized() or self._applying_mode:
            return

        if self.height() < self._normal_minimum_height:
            self._apply_geometry_for_mode((self.width(), self._normal_minimum_height))

    def _apply_route_filter(self) -> None:
        term = self.search_input.text().strip().casefold()
        for category, section in self._route_sections.items():
            visible_count = 0
            for route_name, checkbox in self._route_widgets_by_category[category]:
                visible = self._matches_route(route_name, term)
                checkbox.setVisible(visible)
                if visible:
                    visible_count += 1
            section.setVisible(visible_count > 0)
            section.set_force_open(bool(term) and visible_count > 0)
        self._refresh_recent_routes()

    def _matches_route(self, route_name: str, term: str) -> bool:
        return not term or term in route_name.casefold()

    def _is_pause_mode(self) -> bool:
        """兼容性别名：PAUSED 或 MAXIMIZED 都算非跟踪态（原语义）。"""
        return self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED)

    def _toggle_sidebar(self) -> None:
        self._set_sidebar_collapsed(not self._sidebar_collapsed, restore_size=True)

    def _handle_sidebar_action(self) -> None:
        if self._is_pause_mode():
            self._start_navigation()
            return
        self._toggle_sidebar()

    def _set_sidebar_collapsed(self, collapsed: bool, restore_size: bool) -> None:
        """切换侧边栏可见性。只改可见性 + minimumWidth；尺寸由 _enter_mode 决定。"""
        if collapsed == self._sidebar_collapsed:
            self._apply_sidebar_state()
            return
        restore_geometry = (
            QRect(self.geometry())
            if (
                restore_size
                and not collapsed
                and self._mode in _STABLE_FAMILY
                and self.width() < self._expanded_layout_minimum_width()
            )
            else None
        )
        self._sidebar_collapsed = collapsed
        self._apply_sidebar_state()
        # 若可能（非最大化、有当前 mode 目标尺寸），把窗口重新收敛到当前 mode 的目标尺寸
        if (
            restore_size
            and not self.isMaximized()
            and self._mode != WindowMode.MAXIMIZED
            and not self._applying_mode
        ):
            self._applying_mode = True
            try:
                if collapsed and self._sidebar_expand_restore_geometry is not None:
                    restore = QRect(self._sidebar_expand_restore_geometry)
                    self.setGeometry(restore)
                    self._preferred_right_edge = restore.x() + restore.width()
                    if self._mode in _STABLE_FAMILY:
                        self._size_prefs[WindowMode.TRACKING_STABLE] = (
                            restore.width(),
                            restore.height(),
                        )
                    self._sidebar_expand_restore_geometry = None
                else:
                    self._sidebar_expand_restore_geometry = (
                        QRect(restore_geometry) if restore_geometry is not None else None
                    )
                    self._apply_geometry_for_mode(self._size_for_mode(self._mode))
            finally:
                self._applying_mode = False

    def _expanded_layout_minimum_width(self) -> int:
        root_layout = self.root.layout()
        body_layout = self.body_container.layout()
        root_margins = root_layout.contentsMargins() if root_layout is not None else None
        body_margins = body_layout.contentsMargins() if body_layout is not None else None
        horizontal_padding = self._window_margin * 2
        if root_margins is not None:
            horizontal_padding += root_margins.left() + root_margins.right()
        if body_margins is not None:
            horizontal_padding += body_margins.left() + body_margins.right()
        body_spacing = body_layout.spacing() if body_layout is not None else 0
        return max(
            self._normal_minimum_width,
            self.map_view.minimumWidth()
            + max(self._SIDEBAR_MIN_WIDTH, self._sidebar_width)
            + body_spacing
            + horizontal_padding,
        )

    def _max_sidebar_width_for_current_window(self) -> int:
        """返回在不改变当前窗口宽度前提下，侧边栏允许的最大宽度。"""
        root_layout = self.root.layout()
        body_layout = self.body_container.layout()
        root_margins = root_layout.contentsMargins() if root_layout is not None else None
        body_margins = body_layout.contentsMargins() if body_layout is not None else None
        horizontal_padding = self._window_margin * 2
        if root_margins is not None:
            horizontal_padding += root_margins.left() + root_margins.right()
        if body_margins is not None:
            horizontal_padding += body_margins.left() + body_margins.right()
        body_spacing = body_layout.spacing() if body_layout is not None else 0
        available = self.width() - self.map_view.minimumWidth() - body_spacing - horizontal_padding
        return max(self._SIDEBAR_MIN_WIDTH, available)

    def _sync_window_minimum_width(self) -> None:
        """只负责把 setMinimumWidth 调到正确值；
        实际的 geometry 变动由 _apply_geometry_for_mode 统一管。"""
        # 侧边栏真实可见时（PAUSED 强制展开 / 非折叠），min 必须含侧边栏宽度，
        # 否则 Qt layout 会被动撑开窗口，触发 resizeEvent 连锁问题。
        sidebar_visible = (
            self._mode == WindowMode.PAUSED or not self._sidebar_collapsed
        )
        if sidebar_visible:
            self.setMinimumWidth(self._expanded_layout_minimum_width())
        else:
            self.setMinimumWidth(self._normal_minimum_width)

    def _apply_sidebar_state(self) -> None:
        target_width = max(self._SIDEBAR_MIN_WIDTH, self._sidebar_width)
        if self._is_pause_mode():
            self.sidebar_shell.setVisible(True)
            self.side_scroll.setVisible(True)
            self.sidebar_shell.setMinimumWidth(target_width)
            self.sidebar_shell.setMaximumWidth(target_width)
            self._sync_window_minimum_width()
            self._update_header_button_labels()
            return

        if self._sidebar_collapsed:
            # 完全从布局移除，避免 spacing 仍占右侧空白
            self.sidebar_shell.setVisible(False)
        else:
            self.sidebar_shell.setVisible(True)
            self.side_scroll.setVisible(True)
            self.sidebar_shell.setMinimumWidth(target_width)
            self.sidebar_shell.setMaximumWidth(target_width)
        self._sync_window_minimum_width()
        self._update_header_button_labels()

    def _handle_manual_map_navigation(self) -> None:
        self.map_view.set_center_locked(False)

    def _reset_map_view(self) -> None:
        self.map_view.reset_view()

    def _recent_routes_path(self) -> str:
        return os.path.join(self.route_mgr.base_folder, "recent_routes.json")

    def _load_recent_routes(self) -> list[str]:
        path = self._recent_routes_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        known_routes = {
            route.get("display_name")
            for routes in self.route_mgr.route_groups.values()
            for route in routes
        }
        return [name for name in data if isinstance(name, str) and name in known_routes]

    def _save_recent_routes(self) -> None:
        try:
            with open(self._recent_routes_path(), "w", encoding="utf-8") as f:
                json.dump(self._recent_route_names, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _window_geometry(self) -> QRect:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        total_width = theme.EXPANDED_W + self._window_margin * 2
        total_height = theme.EXPANDED_H + self._window_margin * 2
        x = screen.x() + (screen.width() - total_width) // 2
        y = screen.y() + theme.TOP_MARGIN
        return QRect(x, y, total_width, total_height)

    def _place_on_top_center(self) -> None:
        self.setGeometry(self._window_geometry())

    def _restore_or_center(self) -> None:
        """启动时：位置从 config 恢复；尺寸由启动 mode (PAUSED) 决定。"""
        saved = config.parse_window_geometry(config.WINDOW_GEOMETRY)
        if saved is None or not self._geometry_is_visible(saved):
            self._place_on_top_center()
            return
        # 只用 x/y 的位置，尺寸由 _enter_mode 覆盖
        size = self._size_prefs.get(WindowMode.PAUSED, (saved["width"], saved["height"]))
        self.setGeometry(saved["x"], saved["y"], size[0], size[1])

    # ==========================================================
    # 状态机：WindowMode 切换 + 尺寸应用
    # ==========================================================

    def _enter_mode(self, new_mode: WindowMode) -> None:
        """状态机唯一入口。切换 mode 并应用对应的几何 / 侧边栏 / UI。

        - MAXIMIZED 的进入/离开通过 Qt 的 showMaximized / showNormal。
        - 其它模式用 setGeometry 应用该模式在 _size_prefs 里登记的尺寸。
        - 侧边栏折叠状态独立于 mode；但 PAUSED 会强制展开侧边栏。
        """
        if self._applying_mode:
            return  # 避免 resizeEvent 等回调递归触发
        self._applying_mode = True
        try:
            old_mode = self._mode
            self._mode = new_mode
            if new_mode not in _STABLE_FAMILY:
                self._sidebar_expand_restore_geometry = None

            # MAXIMIZED 进出用系统接口 + 侧边栏特殊处理
            if new_mode == WindowMode.MAXIMIZED:
                # 进入最大化：备份当前侧边栏状态，强制展开 + 固定宽度
                if old_mode != WindowMode.MAXIMIZED:
                    self._geometry_before_max = QRect(self.geometry())
                    self._sidebar_collapsed_before_max = self._sidebar_collapsed
                    self._sidebar_width_before_max = self._sidebar_width
                self._sidebar_collapsed = False
                self._sidebar_width = theme.MAXIMIZED_SIDEBAR_WIDTH
                self._apply_sidebar_state()
                if not self.isMaximized():
                    self.showMaximized()
            else:
                # 从最大化退出：先恢复侧边栏备份
                if old_mode == WindowMode.MAXIMIZED:
                    if self._sidebar_width_before_max is not None:
                        self._sidebar_width = self._sidebar_width_before_max
                        self._sidebar_width_before_max = None
                    if self._sidebar_collapsed_before_max is not None:
                        self._sidebar_collapsed = self._sidebar_collapsed_before_max
                        self._sidebar_collapsed_before_max = None
                if self.isMaximized():
                    self.showNormal()

                # PAUSED 强制展开侧边栏；离开 PAUSED 时恢复之前记住的折叠状态
                if new_mode == WindowMode.PAUSED:
                    if old_mode != WindowMode.PAUSED:
                        # 进入 PAUSED 前记录当前折叠状态
                        self._sidebar_collapsed_before_pause = self._sidebar_collapsed
                        self._sidebar_width_before_pause = self._sidebar_width
                    self._sidebar_width = self._paused_sidebar_width
                    if self._sidebar_collapsed:
                        self._sidebar_collapsed = False
                elif old_mode == WindowMode.PAUSED:
                    # 从 PAUSED 离开 —— 恢复之前的折叠状态
                    self._paused_sidebar_width = self._sidebar_width
                    if self._sidebar_width_before_pause is not None:
                        self._sidebar_width = self._sidebar_width_before_pause
                    if self._sidebar_collapsed_before_pause is not None:
                        self._sidebar_collapsed = self._sidebar_collapsed_before_pause
                        self._sidebar_collapsed_before_pause = None

                self._apply_sidebar_state()

                # STABLE <-> INERTIAL 尺寸一致，跳过 setGeometry 避免每帧抖动
                same_family_shift = (
                    old_mode in _STABLE_FAMILY and new_mode in _STABLE_FAMILY
                )
                if not same_family_shift:
                    target_size = self._size_for_mode(new_mode)
                    self._apply_geometry_for_mode(target_size)
                else:
                    # 只需更新 minimum 高度即可（紧缩态的 setMinimumHeight 遗留）
                    self.setMinimumHeight(self._normal_minimum_height)

            # UI 反馈（alert / 按钮可见性 / 锁定按钮等）
            self._apply_mode_ui(new_mode, old_mode)
            self._schedule_layout_refresh()
        finally:
            self._applying_mode = False

    def _size_for_mode(self, mode: WindowMode) -> tuple[int, int]:
        """返回给定 mode 应该应用到窗口的 (width, height)。"""
        if mode == WindowMode.PAUSED:
            return self._size_prefs[WindowMode.PAUSED]

        # 稳定态：用户偏好；没有则用 PAUSED 的尺寸兜底
        stable_size = self._size_prefs.get(
            WindowMode.TRACKING_STABLE, self._size_prefs[WindowMode.PAUSED]
        )

        if mode in _STABLE_FAMILY:
            return stable_size

        if mode == WindowMode.TRACKING_LOST:
            # 宽度继承稳定态，高度紧缩
            compact_h = getattr(
                self,
                "_compact_minimum_height",
                theme.COMPACT_ALERT_HEIGHT + self._window_margin * 2,
            )
            return (stable_size[0], compact_h)

        # MAXIMIZED 不走这里
        return stable_size

    def _apply_geometry_for_mode(self, size: tuple[int, int]) -> None:
        """把窗口尺寸改为 size，并以"首选右边缘"为锚点定位 x。

        首选右边缘 _preferred_right_edge 在用户手动移动窗口时更新；
        mode 切换导致的宽度变化只改 x（=right_edge - new_width），不动 y。
        这样无论切 mode 几次，右边缘始终不漂，左边缘自然向左/向右挪。
        """
        w, h = size
        # 使用当前 Qt 已知的 minimumWidth（已经由 _sync_window_minimum_width 设好），
        # 这样展开侧边栏时会自动把窗口扩到 layout 需要的最小宽度，避免 Qt 被动撑开。
        w = max(self.minimumWidth(), self._normal_minimum_width, w)

        if self._mode == WindowMode.TRACKING_LOST:
            # 紧缩态：允许比 _normal_minimum_height 更矮
            compact_minimum_height = getattr(
                self,
                "_compact_minimum_height",
                theme.COMPACT_ALERT_HEIGHT + self._window_margin * 2,
            )
            self.setMinimumHeight(compact_minimum_height)
            h = max(compact_minimum_height, h)
        else:
            self.setMinimumHeight(self._normal_minimum_height)
            h = max(self._normal_minimum_height, h)

        geom = self.geometry()
        # 初次调用时 _preferred_right_edge 可能还没建立 — 用当前右边缘初始化
        if self._preferred_right_edge is None:
            self._preferred_right_edge = geom.x() + geom.width()

        new_x = self._preferred_right_edge - w
        new_y = geom.y()
        # 夹紧到当前屏幕可视区
        screen_geo = self._current_screen_available_geometry()
        if screen_geo is not None:
            new_x = max(screen_geo.left(), new_x)
            # 不要超出屏幕右边缘 ——如果可用区宽度不够塞下 w，往左贴屏幕
            if new_x + w > screen_geo.right():
                new_x = max(screen_geo.left(), screen_geo.right() - w)

        self.setGeometry(new_x, new_y, w, h)

    def _apply_mode_ui(
        self, new_mode: WindowMode, old_mode: WindowMode
    ) -> None:
        """按 mode 分派 UI 反馈：alert 面板、按钮可见性、锁定状态等。"""
        # alert 告警面板：只有 TRACKING_LOST 显示
        in_alert = new_mode == WindowMode.TRACKING_LOST
        self._set_alert_mode(in_alert)

        # 暂停态：重置跟踪 flag + 解锁
        if new_mode == WindowMode.PAUSED:
            self._tracking_attempts_paused = True
            if self._locked:
                self._set_locked_state(False)
            self._restore_lock_after_relocate = None
            self._jump_anomaly_count = 0
            self._set_header_action_visibility(False)
            self.state_hint_label.setVisible(False)
        else:
            # 跟踪中/最大化：恢复跟踪
            if old_mode == WindowMode.PAUSED:
                self._tracking_attempts_paused = False
                self._jump_anomaly_count = 0
            # LOST 态（紧缩告警）也不显示侧边栏/重置视图按钮，
            # 紧缩下操作侧边栏没有意义且容易引起布局抖动
            header_visible = (
                new_mode != WindowMode.MAXIMIZED
                and new_mode != WindowMode.TRACKING_LOST
            )
            self._set_header_action_visibility(header_visible)
            if new_mode in _TRACKING_MODES and old_mode != new_mode:
                if new_mode == WindowMode.TRACKING_LOST:
                    self.state_hint_label.setVisible(False)
                else:
                    self.state_hint_label.setVisible(True)
                    if old_mode == WindowMode.PAUSED:
                        self.state_hint_label.setText("正在搜索目标，请稍候…")
                        self.state_hint_label.setStyleSheet("")

        self._update_lock_button_visibility()
        self._update_header_button_labels()

    def _flush_stable_size_to_config(self) -> None:
        """防抖回调：把当前 STABLE 尺寸偏好写回 config.json。"""
        size = self._size_prefs.get(WindowMode.TRACKING_STABLE)
        if size is None:
            return
        try:
            config.save_config({
                "LOCKED_VIEW_SIZE": {
                    "width": int(size[0]),
                    "height": int(size[1]),
                }
            })
        except Exception as e:
            print(f"保存稳定态尺寸失败：{e}")

    def _paint_default_map(self) -> None:
        """启动默认：以原尺寸（zoom=1）居中显示地图中心，
        和跟踪时的视觉一致——view 被地图局部填满，而不是缩成小图。"""
        cx = self.tracker.map_width // 2
        cy = self.tracker.map_height // 2
        self.map_view.preview_relocate(cx, cy, TrackState.SEARCHING)

    def _flush_paused_size_to_config(self) -> None:
        """防抖回调：把当前 PAUSED 尺寸偏好写回 config.json。"""
        size = self._size_prefs.get(WindowMode.PAUSED)
        if size is None:
            return
        try:
            config.save_config({
                "PAUSED_VIEW_SIZE": {
                    "width": int(size[0]),
                    "height": int(size[1]),
                }
            })
        except Exception as e:
            print(f"保存暂停态尺寸失败：{e}")

    def _current_screen_available_geometry(self) -> QRect | None:
        """返回当前窗口所在屏幕的可视区域。"""
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    @staticmethod
    def _geometry_is_visible(g: dict) -> bool:
        """检查保存的 geometry 是否至少和某个屏幕的可视区域相交，避免窗口跑到离线副屏上。"""
        screens = QGuiApplication.screens() or []
        if not screens:
            return True
        saved = QRect(g["x"], g["y"], g["width"], g["height"])
        for s in screens:
            if s.availableGeometry().intersects(saved):
                return True
        return False

    def _save_window_geometry(self) -> None:
        """把当前窗口位置、侧边栏状态、稳定态尺寸写回 config.json。"""
        # 最大化时使用进入前的普通窗口几何，避免把系统最大化后的左上角位置写回配置。
        g = QRect(self.geometry())
        if self._mode == WindowMode.PAUSED:
            tracking_sidebar_collapsed = bool(
                self._sidebar_collapsed_before_pause
                if self._sidebar_collapsed_before_pause is not None
                else self._sidebar_collapsed
            )
            tracking_sidebar_width = int(
                self._sidebar_width_before_pause
                if self._sidebar_width_before_pause is not None
                else self._sidebar_width
            )
            paused_sidebar_width = int(self._sidebar_width)
        elif self._mode == WindowMode.MAXIMIZED:
            if self._geometry_before_max is not None:
                g = QRect(self._geometry_before_max)
            source_mode = self._mode_before_max or WindowMode.PAUSED
            if source_mode == WindowMode.PAUSED:
                tracking_sidebar_collapsed = bool(
                    self._sidebar_collapsed_before_pause
                    if self._sidebar_collapsed_before_pause is not None
                    else config.SIDEBAR_COLLAPSED
                )
                tracking_sidebar_width = int(
                    self._sidebar_width_before_pause
                    if self._sidebar_width_before_pause is not None
                    else config.SIDEBAR_WIDTH
                )
                paused_sidebar_width = int(
                    self._sidebar_width_before_max
                    if self._sidebar_width_before_max is not None
                    else self._paused_sidebar_width
                )
            else:
                tracking_sidebar_collapsed = bool(
                    self._sidebar_collapsed_before_max
                    if self._sidebar_collapsed_before_max is not None
                    else self._sidebar_collapsed
                )
                tracking_sidebar_width = int(
                    self._sidebar_width_before_max
                    if self._sidebar_width_before_max is not None
                    else self._sidebar_width
                )
                paused_sidebar_width = int(self._paused_sidebar_width)
        else:
            tracking_sidebar_collapsed = bool(self._sidebar_collapsed)
            tracking_sidebar_width = int(self._sidebar_width)
            paused_sidebar_width = int(self._paused_sidebar_width)
        payload: dict = {
            "WINDOW_GEOMETRY": {
                "x": int(g.x()),
                "y": int(g.y()),
                "width": int(g.width()),
                "height": int(g.height()),
            },
            "SIDEBAR_COLLAPSED": tracking_sidebar_collapsed,
            "SIDEBAR_WIDTH": tracking_sidebar_width,
            "PAUSED_SIDEBAR_WIDTH": paused_sidebar_width,
        }
        stable = self._size_prefs.get(WindowMode.TRACKING_STABLE)
        if stable is not None:
            payload["LOCKED_VIEW_SIZE"] = {
                "width": int(stable[0]),
                "height": int(stable[1]),
            }
        paused = self._size_prefs.get(WindowMode.PAUSED)
        if paused is not None:
            payload["PAUSED_VIEW_SIZE"] = {
                "width": int(paused[0]),
                "height": int(paused[1]),
            }
        try:
            config.save_config(payload)
        except Exception as e:
            print(f"保存窗口几何失败：{e}")

    def _open_settings(self) -> None:
        from .settings_dialog import open_settings_dialog
        open_settings_dialog(self, on_applied=self._on_settings_applied)

    def _on_settings_applied(self) -> None:
        """设置窗口点击“应用”后回调。config 值已经写回，跟踪循环下次 sleep 自动读新值。"""
        pass

    def _collapse_to_icon(self) -> None:
        """点最小化：隐藏主窗，左上角原位置弹出一个保留状态/坐标的还原胶囊。"""
        if getattr(self, "_mini_icon", None) is not None:
            return
        geom = self.frameGeometry()
        anchor = geom.topLeft()
        self._mini_icon = _RestoreIcon(
            self, self._restore_from_icon, self._close_app_from_icon
        )
        # 把当前已知的状态与坐标灌给小图标，避免切换瞬间显示成默认
        last = getattr(self, "_last_result", None)
        if last is not None:
            self._mini_icon.set_state(last.state)
        self._mini_icon.set_coord(self.coord_label.text())
        self._mini_icon.place_at(anchor)
        self._mini_icon.show()
        self.hide()

    def _restore_from_icon(self) -> None:
        """点小图标：销毁图标并恢复主窗。"""
        icon = getattr(self, "_mini_icon", None)
        if icon is not None:
            icon.close()
            self._mini_icon = None
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _close_app_from_icon(self) -> None:
        """从小图标上的 × 直接关闭程序：关闭所有顶层窗口并退出事件循环。"""
        icon = getattr(self, "_mini_icon", None)
        if icon is not None:
            icon.close()
            self._mini_icon = None
        self._quit_entire_app()

    def _quit_entire_app(self) -> None:
        """强制退出：关所有顶层窗口 + 停跟踪线程 + 退出 QApplication。"""
        self._running = False
        self._stop_hotkey_listener()
        try:
            self.route_mgr.save_progress()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if w is not self:
                    w.close()
            app.quit()
        self.close()

    def _toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            # 退出最大化：回到进入前的 mode
            target = self._mode_before_max or WindowMode.PAUSED
            self._mode_before_max = None
            self._enter_mode(target)
        else:
            # 进入最大化：记录当前 mode 以便退出时恢复
            self._mode_before_max = self._mode
            self._enter_mode(WindowMode.MAXIMIZED)
        self._update_window_controls()
        apply_overlay_flags(self)

    def _update_window_controls(self) -> None:
        self.max_btn.setText("❐" if self.isMaximized() else "▢")
        self._update_header_button_labels()
        self._update_lock_button_visibility()

    def _set_header_button_presentation(
        self,
        button: QPushButton,
        *,
        text: str,
        icon_text: str,
        tooltip: str,
        compact_width: int = 34,
    ) -> None:
        button.setToolTip(tooltip)
        button.setMinimumHeight(26)
        button.setMaximumHeight(26)
        button.setProperty("headerIconOnly", self._header_buttons_icon_only)
        if self._header_buttons_icon_only:
            button.setText(icon_text)
            button.setMinimumWidth(compact_width)
            button.setMaximumWidth(compact_width)
        else:
            button.setText(text)
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _update_header_button_labels(self) -> None:
        if self._is_pause_mode():
            sidebar_text = "开始导航"
            sidebar_icon = "导"
        elif self._sidebar_collapsed:
            sidebar_text = "展开侧边栏"
            sidebar_icon = "展"
        else:
            sidebar_text = "隐藏侧边栏"
            sidebar_icon = "隐"

        lock_text = "解锁" if self._locked else "锁定"
        lock_icon = "🔓" if self._locked else "🔒"

        # PAUSED 下第一个操作按钮改为"开始导航"；跟踪中保持"重定位"
        is_paused = self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED)
        action_text = "开始导航" if is_paused else "重定位"
        action_icon = "导" if is_paused else "⌖"

        button_specs = [
            {
                "button": self.relocate_btn,
                "text": action_text,
                "icon_text": action_icon,
                "tooltip": action_text,
                "compact_width": 34,
            },
            {
                "button": self.reset_view_btn,
                "text": "重置视图",
                "icon_text": "↺",
                "tooltip": "重置视图",
                "compact_width": 34,
            },
            {
                "button": self.sidebar_toggle_btn,
                "text": sidebar_text,
                "icon_text": sidebar_icon,
                "tooltip": sidebar_text,
                "compact_width": 34,
            },
            {
                "button": self.terminate_nav_btn,
                "text": "终止导航",
                "icon_text": "止",
                "tooltip": "终止导航",
                "compact_width": 34,
            },
            {
                "button": self.lock_btn,
                "text": lock_text,
                "icon_text": lock_icon,
                "tooltip": lock_text,
                "compact_width": 34,
            },
        ]

        self._header_buttons_icon_only = self.width() < self._HEADER_ICON_SWITCH_WIDTH

        for spec in button_specs:
            self._set_header_button_presentation(
                spec["button"],
                text=spec["text"],
                icon_text=spec["icon_text"],
                tooltip=spec["tooltip"],
                compact_width=spec["compact_width"],
            )

    def _update_lock_button_visibility(self) -> None:
        visible = self._mode in _STABLE_FAMILY
        self.terminate_nav_btn.setVisible(visible)
        self.lock_btn.setVisible(visible)

    def _can_toggle_lock(self) -> bool:
        return self._mode in _STABLE_FAMILY

    def _set_locked_state(self, locked: bool) -> None:
        self._locked = locked
        self.lock_btn.setChecked(self._locked)
        self._update_header_button_labels()
        self.unlock_hint_label.setVisible(self._locked)
        if self._locked:
            set_click_through(self, True)
            self.setWindowOpacity(0.78)
        else:
            set_click_through(self, False)
            self.setWindowOpacity(1.0)

    def _enter_lost_mode(self) -> None:
        """进入 LOST 状态：记录锁定偏好后解锁，然后切状态机。"""
        if self._mode == WindowMode.TRACKING_LOST:
            return
        if self._mode in _STABLE_FAMILY:
            # 从稳定态跌入 LOST 前，记录锁定偏好便于恢复后回填
            self._lock_state_before_lost = self._preferred_locked
        if self._locked:
            self._set_locked_state(False)
        self._enter_mode(WindowMode.TRACKING_LOST)
        self._update_lock_button_visibility()

    def _exit_lost_mode(self, clear_saved_lock_state: bool = True) -> None:
        """退出 LOST 状态。真正的 mode 切换由调用者决定（进 STABLE 还是 PAUSED）。"""
        if self._mode != WindowMode.TRACKING_LOST:
            return
        if clear_saved_lock_state:
            self._lock_state_before_lost = None
        self._update_lock_button_visibility()

    def _restore_lock_state_after_lost(self) -> None:
        desired_locked = self._lock_state_before_lost
        if desired_locked is None:
            desired_locked = self._preferred_locked
        self._exit_lost_mode(clear_saved_lock_state=False)
        self._lock_state_before_lost = None
        if desired_locked is not None and self._locked != desired_locked:
            self._set_locked_state(desired_locked)
        self._update_lock_button_visibility()

    def _reset_tracker_after_pause(self) -> None:
        self._resume_tracking_attempts()
        self._latencies.clear()
        self._last_player_xy = None
        self._jump_anomaly_count = 0
        self._clear_tracker_anchor()
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def _clear_tracker_anchor(self) -> None:
        for attr in ("_last_x", "_last_y"):
            if hasattr(self.tracker, attr):
                setattr(self.tracker, attr, None)
        if hasattr(self.tracker, "_lost_frames"):
            setattr(self.tracker, "_lost_frames", 0)

    def _start_hotkey_listener(self) -> None:
        if self._is_windows and self._start_native_hotkey_listener():
            return
        if keyboard is None:
            return

        def on_press(key):
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self._alt_pressed = True
                return
            if getattr(key, "vk", None) != 0xC0 or not self._alt_pressed:
                return
            self._request_toggle_lock()

        def on_release(key):
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self._alt_pressed = False

        self._hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._hotkey_listener.daemon = True
        self._hotkey_listener.start()

    def _request_toggle_lock(self) -> None:
        if not self._can_toggle_lock():
            return
        now = time.monotonic()
        if now - self._last_hotkey_at < self._HOTKEY_DEBOUNCE_SEC:
            return
        self._last_hotkey_at = now
        self._toggle_lock_requested.emit()

    def _start_native_hotkey_listener(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return False

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        wm_hotkey = 0x0312
        mod_alt = 0x0001
        mod_norepeat = 0x4000
        vk_oem_3 = 0xC0

        def hotkey_loop():
            self._hotkey_thread_id = kernel32.GetCurrentThreadId()
            registered_hotkey = bool(
                user32.RegisterHotKey(
                    None,
                    self._NATIVE_HOTKEY_ID_ALT_GRAVE,
                    mod_alt | mod_norepeat,
                    vk_oem_3,
                )
            )
            if not registered_hotkey:
                self._hotkey_thread_id = None
                return

            message = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
                    if (
                        message.message == wm_hotkey
                        and message.wParam == self._NATIVE_HOTKEY_ID_ALT_GRAVE
                    ):
                        self._request_toggle_lock()
            finally:
                if registered_hotkey:
                    user32.UnregisterHotKey(None, self._NATIVE_HOTKEY_ID_ALT_GRAVE)
                self._hotkey_thread_id = None

        self._hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
        self._hotkey_thread.start()
        time.sleep(0.05)
        return self._hotkey_thread_id is not None

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

        if self._hotkey_thread_id is not None:
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, 0x0012, 0, 0)
            except Exception:
                pass

        if self._hotkey_thread is not None:
            self._hotkey_thread.join(timeout=0.5)
            self._hotkey_thread = None

    def _install_resize_filters(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)
            child.setMouseTracking(True)

    def _resize_edges_at(self, global_pos) -> Qt.Edges:
        if self.isMaximized():
            return Qt.Edges()
        local = self.mapFromGlobal(global_pos)
        left = local.x() <= self._RESIZE_MARGIN
        right = local.x() >= self.width() - self._RESIZE_MARGIN
        top = local.y() <= self._RESIZE_MARGIN
        bottom = local.y() >= self.height() - self._RESIZE_MARGIN

        edges = Qt.Edges()
        if left:
            edges |= Qt.LeftEdge
        if right:
            edges |= Qt.RightEdge
        if top:
            edges |= Qt.TopEdge
        if bottom:
            edges |= Qt.BottomEdge
        return edges

    def _cursor_for_edges(self, edges: Qt.Edges):
        if edges in (Qt.LeftEdge, Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges in (Qt.TopEdge, Qt.BottomEdge):
            return Qt.SizeVerCursor
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        return None

    def _update_resize_cursor(self, global_pos) -> None:
        cursor = self._cursor_for_edges(self._resize_edges_at(global_pos))
        if cursor is None:
            if self._edge_cursor_active:
                self.unsetCursor()
                self._edge_cursor_active = False
            return
        self.setCursor(QCursor(cursor))
        self._edge_cursor_active = True

    def _resume_tracking_attempts(self) -> None:
        self._tracking_attempts_paused = False
        self._tracking_paused_state = TrackState.SEARCHING
        self._jump_anomaly_count = 0
        self._apply_sidebar_state()
        self._update_lock_button_visibility()

    def _start_navigation(self) -> None:
        """用户点"开始导航"（或从最大化的开始导航按钮进入）。
        进入 TRACKING_STABLE 作为基准；跟踪循环会根据首帧真实状态自动切 LOST/INERTIAL。"""
        self._mode_before_max = None  # 从任何态主动开始导航，放弃最大化恢复记录
        self._sync_normal_minimum_height()
        self.setMinimumHeight(self._normal_minimum_height)
        self._resume_tracking_attempts()
        self._enter_mode(WindowMode.TRACKING_STABLE)
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def _paused_track_result(self) -> TrackResult:
        x = y = None
        if self._tracking_paused_state == TrackState.INERTIAL and self._last_player_xy is not None:
            x, y = self._last_player_xy
        return TrackResult(self._tracking_paused_state, x=x, y=y, latency_ms=0.0)

    def _pause_navigation(self) -> None:
        """用户点"停止导航"。切回 PAUSED 态，固定尺寸 + 强制展开侧边栏。"""
        self._mode_before_max = None
        self._restore_lock_after_relocate = None
        self._tracking_paused_state = TrackState.SEARCHING
        self._enter_mode(WindowMode.PAUSED)
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def _restore_from_compact_mode(self) -> None:
        """兼容 shim：原语义是"退出紧缩"。现由 _enter_mode 统管。"""
        if self._mode == WindowMode.TRACKING_LOST:
            # 若有调用方期望退出紧缩，由状态机下次转入 STABLE/INERTIAL 自然还原
            self.setMinimumHeight(self._normal_minimum_height)

    def _sidebar_resize_hit(self, global_pos) -> bool:
        if self._sidebar_collapsed and not self._is_pause_mode():
            return False
        if not self.sidebar_shell.isVisible():
            return False
        local = self.sidebar_shell.mapFromGlobal(global_pos)
        return (
            0 <= local.x() <= self._SIDEBAR_RESIZE_MARGIN
            and 0 <= local.y() <= self.sidebar_shell.height()
        )

    def _resize_sidebar(self, global_x: int) -> None:
        delta = global_x - self._sidebar_resize_start_x
        max_width = self._max_sidebar_width_for_current_window()
        self._sidebar_width = max(
            self._SIDEBAR_MIN_WIDTH,
            min(max_width, self._sidebar_resize_start_width - delta),
        )
        self._apply_sidebar_state()

    def _set_alert_mode(self, enabled: bool, message: str = "", allow_terminate: bool = False) -> None:
        self.alert_card.setVisible(enabled)
        self.body_container.setVisible(not enabled)
        self.state_hint_label.setVisible(not enabled)
        if enabled and message:
            self.alert_message.setText(message)
        self.alert_terminate_btn.setVisible(allow_terminate)

    def _set_header_action_visibility(self, visible: bool) -> None:
        is_paused = self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED)
        is_lost = self._mode == WindowMode.TRACKING_LOST
        self.relocate_btn.setVisible(visible or is_paused or is_lost)
        # 暂停态保留“开始导航”和“重置视图”；丢失态恢复右上角“重定位”。
        self.relocate_btn.setVisible(visible or is_paused or is_lost)
        self.reset_view_btn.setVisible((visible or is_paused) and not is_lost)
        self.sidebar_toggle_btn.setVisible(visible and not is_paused and not is_lost)

    def _enter_compact_mode(self) -> None:
        """兼容 shim：原语义是"进入紧缩"。现在统一由 _enter_mode(TRACKING_LOST) 做。"""
        if self._mode != WindowMode.TRACKING_LOST and not self.isMaximized():
            self._enter_mode(WindowMode.TRACKING_LOST)

    def _exit_compact_mode(self) -> None:
        """兼容 shim。"""
        self._restore_from_compact_mode()

    def _apply_state_feedback(self, state: TrackState) -> None:
        """根据跟踪器状态更新 UI 文案；若 mode 需要切换，调用 _enter_mode。"""
        # PAUSED / MAXIMIZED 不跟随 tracker 状态
        if self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED):
            self._restore_lock_state_after_lost()
            self._set_alert_mode(False)
            if self._mode == WindowMode.PAUSED:
                self.state_hint_label.setText("暂停定位")
                self.state_hint_label.setStyleSheet("")
            return

        # 将 tracker 状态映射为目标 mode
        if state == TrackState.SEARCHING:
            if self._mode == WindowMode.TRACKING_LOST:
                target_mode = WindowMode.TRACKING_LOST
            elif self._mode in _STABLE_FAMILY:
                target_mode = self._mode
            else:
                target_mode = WindowMode.TRACKING_STABLE
        else:
            target_mode = _tracker_state_to_mode(state)
        # SEARCHING 归 LOST，但文字不同；如果当前锁定偏好需要恢复先做
        if target_mode != self._mode:
            if target_mode in _STABLE_FAMILY and self._mode == WindowMode.TRACKING_LOST:
                # 恢复锁定偏好
                self._restore_lock_state_after_lost()
            if target_mode == WindowMode.TRACKING_LOST:
                self._enter_lost_mode()
            else:
                self._enter_mode(target_mode)

        # 文案
        if state == TrackState.LOCKED:
            self._set_alert_mode(False)
            self.state_hint_label.setVisible(True)
            self.state_hint_label.setText("定位稳定")
            self.state_hint_label.setStyleSheet("")
        elif state == TrackState.INERTIAL:
            self._set_alert_mode(False)
            self.state_hint_label.setVisible(True)
            self.state_hint_label.setText("定位暂时不稳定，沿用上一帧位置。")
            self.state_hint_label.setStyleSheet("")
        elif state == TrackState.SEARCHING:
            self._jump_anomaly_count = 0
            self._set_alert_mode(False)
            self.state_hint_label.setVisible(True)
            self.state_hint_label.setText("正在搜索目标，请稍候…")
            self.state_hint_label.setStyleSheet("")
        else:  # LOST
            self._set_alert_mode(True, "目标丢失，正在持续尝试重新定位。", allow_terminate=True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and hasattr(event, "globalPosition") and event.button() == Qt.LeftButton:
            if self._sidebar_resize_hit(event.globalPosition().toPoint()):
                self._sidebar_resizing = True
                self._sidebar_resize_start_x = event.globalPosition().toPoint().x()
                self._sidebar_resize_start_width = self._sidebar_width
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return True

        if event.type() == QEvent.MouseMove and hasattr(event, "globalPosition"):
            if self._sidebar_resizing:
                self._resize_sidebar(event.globalPosition().toPoint().x())
                return True
            if self._sidebar_resize_hit(event.globalPosition().toPoint()):
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return False

        if event.type() == QEvent.MouseButtonRelease and self._sidebar_resizing:
            self._sidebar_resizing = False
            return True

        if watched is self.title_drag_area:
            if (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and not self.isMaximized()
            ):
                self._move_dragging = True
                self._move_drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and self._move_dragging and event.buttons() & Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._move_drag_offset)
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._move_dragging = False
                self._move_drag_offset = None
                return True

        if event.type() == QEvent.MouseMove and hasattr(event, "globalPosition"):
            self._update_resize_cursor(event.globalPosition().toPoint())
        elif event.type() == QEvent.Leave and not self._move_dragging:
            if self._edge_cursor_active:
                self.unsetCursor()
                self._edge_cursor_active = False

        if (
            event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
            and not self.isMaximized()
        ):
            edges = self._resize_edges_at(event.globalPosition().toPoint())
            if edges and self.windowHandle() is not None and self.windowHandle().startSystemResize(edges):
                return True

        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.AltModifier and event.key() in (Qt.Key_QuoteLeft, Qt.Key_AsciiTilde):
            if self._can_toggle_lock():
                self.toggle_lock()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_controls()

        # 注意：这里 *不* 更新 _preferred_right_edge（防止 layout 被动撑开污染锚点）。
        # 只在 moveEvent（用户拖标题栏）时更新。

        if self.isMaximized() or self._applying_mode:
            return

        # STABLE/INERTIAL 家族且侧边栏"未展开"时记忆稳定态尺寸。
        # 展开侧边栏引起的 layout 被动撑开不应被记忆，否则收起后恢复不到原始大小。
        if self._mode in _STABLE_FAMILY:
            self._size_prefs[WindowMode.TRACKING_STABLE] = (self.width(), self.height())
            self._stable_size_save_timer.start()
        elif self._mode == WindowMode.PAUSED:
            # PAUSED 的侧边栏永远强制展开，所以不设"折叠"条件；
            # 用户在 PAUSED 下对窗口的任何 resize 都视为用户偏好。
            self._size_prefs[WindowMode.PAUSED] = (self.width(), self.height())
            self._paused_size_save_timer.start()

    def moveEvent(self, event):
        super().moveEvent(event)
        # 用户手动拖动窗口时，更新锚点右边缘。状态机自己做的 setGeometry
        # 通过 _applying_mode 过滤掉，避免把状态机 set 的右边缘当"用户偏好"。
        if not self._applying_mode and not self.isMaximized():
            self._preferred_right_edge = self.x() + self.width()

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_flags(self)

    def closeEvent(self, event):
        self._running = False
        self._stop_hotkey_listener()
        self.route_mgr.save_visibility()
        self.route_mgr.save_progress()
        self._save_window_geometry()
        # 关闭可能还开着的设置窗等顶层窗口，确保进程彻底退出
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if w is not self:
                    w.close()
            app.quit()
        super().closeEvent(event)

    def toggle_lock(self) -> None:
        if not self._can_toggle_lock():
            return
        self._preferred_locked = not self._locked
        self._set_locked_state(self._preferred_locked)

    def _prompt_relocate(self) -> None:
        # PAUSED 下按下这个按钮意味着"开始导航"
        if self._mode == WindowMode.PAUSED:
            self._start_navigation()
            return

        if self._mode == WindowMode.TRACKING_LOST:
            self._restore_lock_after_relocate = self._preferred_locked
            self._exit_lost_mode()
        else:
            self._restore_lock_after_relocate = self._preferred_locked
        self._resume_tracking_attempts()
        self._restore_from_compact_mode()
        self._set_alert_mode(False)
        self._set_header_action_visibility(True)
        self.state_hint_label.setVisible(True)
        self.state_hint_label.setText("正在搜索目标，请稍候…")
        self.state_hint_label.setStyleSheet("")
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))
        self.map_view.preview_relocate(
            self.tracker.map_width // 2,
            self.tracker.map_height // 2,
            TrackState.SEARCHING,
        )

    def _on_relocate(self, x: int, y: int) -> None:
        """双击地图：只在地图上标记选点位置，不自动开始导航。

        - PAUSED 态：更新 tracker anchor + 预览标记，保持暂停状态。
        - 跟踪态：维持原行为（作为重定位触发）。
        """
        self.tracker.set_anchor(x, y)
        self.map_view.preview_relocate(x, y, TrackState.SEARCHING)
        self.coord_label.setText(f"{x} , {y}")
        self._last_player_xy = (x, y)

        if self._mode == WindowMode.PAUSED:
            # 暂停下：仅标记选点，不恢复跟踪、不发事件
            return

        self._resume_tracking_attempts()
        if self._restore_lock_after_relocate is not None:
            self._set_locked_state(self._restore_lock_after_relocate)
            self._restore_lock_after_relocate = None
            self._update_lock_button_visibility()
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, x=x, y=y, latency_ms=0.0))

    def _tracker_loop(self) -> None:
        def _current_refresh_ms() -> int:
            return int(
                config.AI_REFRESH_RATE if hasattr(self.tracker, "engine")
                else config.SIFT_REFRESH_RATE
            )

        while self._running:
            if self.isMaximized():
                self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))
                time.sleep(_current_refresh_ms() / 1000.0)
                continue

            if self._tracking_attempts_paused:
                self._frame_ready.emit(self._paused_track_result())
                time.sleep(_current_refresh_ms() / 1000.0)
                continue

            with mss.mss() as sct:
                while self._running and not self.isMaximized() and not self._tracking_attempts_paused:
                    refresh_ms = _current_refresh_ms()
                    started_at = time.time()
                    try:
                        shot = sct.grab(self._minimap_region)
                        minimap_bgr = np.array(shot)[:, :, :3]
                    except Exception:
                        time.sleep(0.1)
                        continue

                    self._latest_minimap = minimap_bgr
                    result = self.tracker.step(minimap_bgr)
                    self._frame_ready.emit(result)

                    elapsed_ms = (time.time() - started_at) * 1000.0
                    wait_seconds = max(0.0, (refresh_ms - elapsed_ms) / 1000.0)
                    time.sleep(wait_seconds)

    def _on_frame(self, result: TrackResult) -> None:
        state = TrackState.SEARCHING if self.isMaximized() else result.state
        if (
            not self.isMaximized()
            and not self._tracking_attempts_paused
            and state == TrackState.LOCKED
            and result.x is not None
            and result.y is not None
        ):
            if self._last_player_xy is not None:
                jump = max(
                    abs(result.x - self._last_player_xy[0]),
                    abs(result.y - self._last_player_xy[1]),
                )
                if jump >= theme.TRACK_JUMP_DETECT_THRESHOLD:
                    self._jump_anomaly_count += 1
                else:
                    self._jump_anomaly_count = 0

                if self._jump_anomaly_count >= theme.TRACK_JUMP_DETECT_LIMIT:
                    self._jump_anomaly_count = 0
                    self._clear_tracker_anchor()
                    self._last_player_xy = None
                    state = TrackState.LOST
                    result = TrackResult(TrackState.LOST, latency_ms=result.latency_ms)
            else:
                self._jump_anomaly_count = 0
        elif state != TrackState.LOCKED:
            self._jump_anomaly_count = 0

        self._last_result = result
        self.dot.set_state(state)
        mini = getattr(self, "_mini_icon", None)
        if mini is not None:
            mini.set_state(state)
        self._apply_state_feedback(state)
        self._latencies.append(result.latency_ms)

        avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        fps = 1000.0 / avg_latency if avg_latency > 0 else 0.0

        if not self.isMaximized() and result.x is not None and result.y is not None:
            coord_text = f"{result.x} , {result.y}"
            self.coord_label.setText(coord_text)
            if self._last_player_xy is not None:
                dx = abs(result.x - self._last_player_xy[0])
                dy = abs(result.y - self._last_player_xy[1])
                if max(dx, dy) >= self._AUTO_RECENTER_MOVE_THRESHOLD:
                    self.map_view.set_center_locked(True)
            self._last_player_xy = (result.x, result.y)
            self.map_view.update_frame(result.state, result.x, result.y, self._latest_minimap)
        elif self.isMaximized():
            coord_text = "-- , --"
            self.coord_label.setText(coord_text)
        else:
            coord_text = "-- , --"
            self.coord_label.setText(coord_text)

        if mini is not None:
            mini.set_coord(coord_text)

        self.stat_label.setText(f"{avg_latency:4.0f} ms · {fps:4.1f} fps")


class _RestoreIcon(QWidget):
    """最小化后显示在左上角的小胶囊：状态球 + 当前坐标 + 还原按钮。支持拖动。"""

    _HEIGHT = 44

    def __init__(self, island_owner, on_restore, on_close) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(theme.ISLAND_QSS)
        self._on_restore = on_restore
        self._on_close_app = on_close
        self._drag_offset = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("IslandRoot")
        outer.addWidget(shell)

        row = QHBoxLayout(shell)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(8)

        self.dot = _StatusDot(shell)
        self.dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.dot, alignment=Qt.AlignVCenter)

        self.coord_label = QLabel("-- , --", shell)
        self.coord_label.setObjectName("CoordLabel")
        self.coord_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.coord_label, alignment=Qt.AlignVCenter)

        restore_btn = QPushButton("▣")
        restore_btn.setObjectName("WindowControl")
        restore_btn.setFixedSize(self._HEIGHT - 12, self._HEIGHT - 12)
        restore_btn.setToolTip("还原窗口")
        restore_btn.setStyleSheet("font-size: 14px;")
        restore_btn.setCursor(Qt.PointingHandCursor)
        restore_btn.clicked.connect(self._on_restore)
        row.addWidget(restore_btn, alignment=Qt.AlignVCenter)

        close_btn = QPushButton("×")
        close_btn.setObjectName("WindowControl")
        close_btn.setFixedSize(self._HEIGHT - 12, self._HEIGHT - 12)
        close_btn.setToolTip("关闭程序")
        close_btn.setStyleSheet("font-size: 16px;")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._on_close_app)
        row.addWidget(close_btn, alignment=Qt.AlignVCenter)

        self.setCursor(Qt.SizeAllCursor)
        self.setFixedHeight(self._HEIGHT)
        self.adjustSize()

    def set_state(self, state: TrackState) -> None:
        self.dot.set_state(state)

    def set_coord(self, text: str) -> None:
        self.coord_label.setText(text)

    def place_at(self, top_left) -> None:
        self.move(top_left.x(), top_left.y())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)
