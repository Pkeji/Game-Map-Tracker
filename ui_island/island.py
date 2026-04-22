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

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
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
        self._expanded = True
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

    def __init__(self, tracker: BaseTracker, route_mgr: RouteManager) -> None:
        super().__init__(None)
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

        self._sidebar_collapsed = False
        self._expanded_size_memory: tuple[int, int] | None = None
        self._collapsed_size_memory: tuple[int, int] | None = None
        self._sidebar_collapsed_before_maximize: bool | None = None
        self._restore_geometry_before_maximize: QRect | None = None
        self._sidebar_width = 320

        self._compact_state_active = False
        self._compact_restore_geometry: QRect | None = None
        self._compact_restore_sidebar_collapsed = False

        self._normal_minimum_width = theme.WINDOW_MIN_W + self._window_margin * 2
        self._normal_minimum_height = theme.WINDOW_MIN_H + self._window_margin * 2
        self._tracking_attempts_paused = False
        self._tracking_paused_state = TrackState.SEARCHING
        self._manual_pause = False
        self._jump_anomaly_count = 0
        self._lost_mode_active = False
        self._preferred_locked = False
        self._lock_state_before_lost: bool | None = None
        self._restore_lock_after_relocate: bool | None = None

        self._move_dragging = False
        self._move_drag_offset = None
        self._edge_cursor_active = False
        self._sidebar_resizing = False
        self._sidebar_resize_start_x = 0
        self._sidebar_resize_start_width = self._sidebar_width

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)

        self._build_ui()
        self._install_resize_filters(self.root)
        self.installEventFilter(self)
        self._place_on_top_center()

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
        self.min_btn.setToolTip("最小化为小图标")
        self.min_btn.clicked.connect(self._collapse_to_icon)
        header.addWidget(self.min_btn)

        self.max_btn = QPushButton("▢")
        self.max_btn.setObjectName("WindowControl")
        self.max_btn.clicked.connect(self._toggle_maximize_restore)
        header.addWidget(self.max_btn)

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WindowControl")
        self.close_btn.clicked.connect(self.close)
        header.addWidget(self.close_btn)

        self.relocate_btn = QPushButton("重定位")
        self.relocate_btn.clicked.connect(self._prompt_relocate)
        header.addWidget(self.relocate_btn)

        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.clicked.connect(self._reset_map_view)
        header.addWidget(self.reset_view_btn)

        self.sidebar_toggle_btn = QPushButton("隐藏侧边栏")
        self.sidebar_toggle_btn.setObjectName("TopSidebarToggle")
        self.sidebar_toggle_btn.clicked.connect(self._handle_sidebar_action)
        header.addWidget(self.sidebar_toggle_btn)

        self.lock_btn = QPushButton("锁定")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setFixedSize(48, 24)
        self.lock_btn.clicked.connect(self.toggle_lock)
        header.addWidget(self.lock_btn)

        root_layout.addLayout(header)

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

        self.map_view = MapView(self.route_mgr)
        self.map_view.set_maps(self.tracker.display_map_bgr)
        self.map_view.relocate_requested.connect(self._on_relocate)
        self.map_view.manual_view_changed.connect(self._handle_manual_map_navigation)
        body.addWidget(self.map_view, stretch=7)

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

        map_hint = QLabel("滚轮缩放，左键拖动，双击重定位")
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

        routes_scroll = QScrollArea()
        routes_scroll.setWidgetResizable(True)
        routes_scroll.setFrameShape(QFrame.NoFrame)
        routes_scroll.viewport().setAutoFillBackground(False)

        routes_scroll_inner = QWidget()
        routes_scroll_inner.setObjectName("RoutesScrollInner")
        routes_scroll_inner.setAttribute(Qt.WA_StyledBackground, True)
        self.routes_layout = QVBoxLayout(routes_scroll_inner)
        self.routes_layout.setContentsMargins(0, 0, 0, 0)
        self.routes_layout.setSpacing(8)
        self._build_route_sections()
        self.routes_layout.addStretch()
        routes_scroll.setWidget(routes_scroll_inner)
        side_layout.addWidget(routes_scroll, stretch=1)

        self.side_scroll.setWidget(self.side_panel)
        shell_layout.addWidget(self.side_scroll, stretch=1)

        body.addWidget(self.sidebar_shell, stretch=4)
        root_layout.addWidget(self.body_container, stretch=1)

        self.map_view.set_center_locked(True)
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
        self._sync_route_checkboxes(name, enabled, source)
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
        return self._manual_pause or self.isMaximized()

    def _toggle_sidebar(self) -> None:
        self._set_sidebar_collapsed(not self._sidebar_collapsed, restore_size=True)

    def _handle_sidebar_action(self) -> None:
        if self._is_pause_mode():
            self._start_navigation()
            return
        self._toggle_sidebar()

    def _set_sidebar_collapsed(self, collapsed: bool, restore_size: bool) -> None:
        if collapsed == self._sidebar_collapsed:
            self._apply_sidebar_state()
            return

        geom = self.geometry()
        if not self.isMaximized():
            if collapsed:
                if geom.width() >= theme.SIDEBAR_MIN_EXPANDED_W or self._expanded_size_memory is None:
                    self._expanded_size_memory = (
                        max(theme.SIDEBAR_MIN_EXPANDED_W, geom.width()),
                        max(theme.SIDEBAR_MIN_EXPANDED_H, geom.height()),
                    )
            else:
                self._collapsed_size_memory = (geom.width(), geom.height())

        self._sidebar_collapsed = collapsed
        self._apply_sidebar_state()

        if restore_size and not self.isMaximized() and not self._compact_state_active:
            x, y = geom.x(), geom.y()
            if collapsed:
                target = self._collapsed_size_memory or (geom.width(), geom.height())
                self.setGeometry(
                    x,
                    y,
                    max(self._normal_minimum_width, target[0]),
                    max(self._normal_minimum_height, target[1]),
                )
            else:
                target = self._expanded_size_memory or (geom.width(), geom.height())
                self.setGeometry(
                    x,
                    y,
                    max(theme.SIDEBAR_MIN_EXPANDED_W, target[0]),
                    max(theme.SIDEBAR_MIN_EXPANDED_H, target[1]),
                )

    def _apply_sidebar_state(self) -> None:
        target_width = max(self._SIDEBAR_MIN_WIDTH, self._sidebar_width)
        if self._is_pause_mode():
            self.sidebar_shell.setVisible(True)
            self.side_scroll.setVisible(True)
            self.sidebar_shell.setMinimumWidth(target_width)
            self.sidebar_shell.setMaximumWidth(target_width)
            self.sidebar_toggle_btn.setText("开始导航")
            return

        if self._sidebar_collapsed:
            # 完全从布局移除，避免 spacing 仍占右侧空白
            self.sidebar_shell.setVisible(False)
            self.sidebar_toggle_btn.setText("展开侧边栏")
        else:
            self.sidebar_shell.setVisible(True)
            self.side_scroll.setVisible(True)
            self.sidebar_shell.setMinimumWidth(target_width)
            self.sidebar_shell.setMaximumWidth(target_width)
            self.sidebar_toggle_btn.setText("隐藏侧边栏")

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
            self.showNormal()
            if self._restore_geometry_before_maximize is not None:
                self.setGeometry(self._restore_geometry_before_maximize)
            self._restore_geometry_before_maximize = None
            self._sidebar_collapsed_before_maximize = None
            self._pause_navigation()
        else:
            if self._compact_state_active:
                self._exit_compact_mode()
            self._restore_geometry_before_maximize = self.geometry()
            self._sidebar_collapsed_before_maximize = self._sidebar_collapsed
            if self._sidebar_collapsed:
                self._set_sidebar_collapsed(False, restore_size=False)
            self.showMaximized()
        self._apply_sidebar_state()
        self._update_window_controls()
        apply_overlay_flags(self)

    def _update_window_controls(self) -> None:
        self.max_btn.setText("❐" if self.isMaximized() else "▢")
        self._update_lock_button_visibility()

    def _update_lock_button_visibility(self) -> None:
        self.lock_btn.setVisible(not self.isMaximized() and not self._lost_mode_active and not self._manual_pause)

    def _can_toggle_lock(self) -> bool:
        return not self.isMaximized() and not self._manual_pause and not self._lost_mode_active

    def _set_locked_state(self, locked: bool) -> None:
        self._locked = locked
        self.lock_btn.setChecked(self._locked)
        self.lock_btn.setText("解锁" if self._locked else "锁定")
        self.unlock_hint_label.setVisible(self._locked)
        if self._locked:
            set_click_through(self, True)
            self.setWindowOpacity(0.78)
        else:
            set_click_through(self, False)
            self.setWindowOpacity(1.0)

    def _enter_lost_mode(self) -> None:
        if self._lost_mode_active:
            return
        self._lost_mode_active = True
        self._lock_state_before_lost = self._preferred_locked
        if self._locked:
            self._set_locked_state(False)
        self._update_lock_button_visibility()

    def _exit_lost_mode(self, clear_saved_lock_state: bool = True) -> None:
        if not self._lost_mode_active:
            return
        self._lost_mode_active = False
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
        self._manual_pause = False
        self._jump_anomaly_count = 0
        self._apply_sidebar_state()
        self._update_lock_button_visibility()

    def _start_navigation(self) -> None:
        if self.isMaximized():
            self.showNormal()
            if self._restore_geometry_before_maximize is not None:
                self.setGeometry(self._restore_geometry_before_maximize)
            self._restore_geometry_before_maximize = None
            self._sidebar_collapsed_before_maximize = None
        self._resume_tracking_attempts()
        self._set_sidebar_collapsed(False, restore_size=False)
        self._set_alert_mode(False)
        self._set_header_action_visibility(True)
        self.state_hint_label.setVisible(True)
        self.state_hint_label.setText("正在搜索目标，请稍候…")
        self.state_hint_label.setStyleSheet("")
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def _paused_track_result(self) -> TrackResult:
        x = y = None
        if self._tracking_paused_state == TrackState.INERTIAL and self._last_player_xy is not None:
            x, y = self._last_player_xy
        return TrackResult(self._tracking_paused_state, x=x, y=y, latency_ms=0.0)

    def _pause_navigation(self) -> None:
        self._restore_from_compact_mode()
        self._exit_lost_mode()
        self._restore_lock_after_relocate = None
        if self._locked:
            self._set_locked_state(False)
        self._tracking_attempts_paused = True
        self._tracking_paused_state = TrackState.SEARCHING
        self._manual_pause = True
        self._jump_anomaly_count = 0
        self._set_sidebar_collapsed(False, restore_size=not self.isMaximized())
        self._apply_sidebar_state()
        self._update_lock_button_visibility()
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def _restore_from_compact_mode(self) -> None:
        if not self._compact_state_active:
            return

        restore_geometry = self._compact_restore_geometry
        restore_sidebar = self._compact_restore_sidebar_collapsed
        self._compact_state_active = False
        self._compact_restore_geometry = None
        self._compact_restore_sidebar_collapsed = False
        self.setMinimumHeight(self._normal_minimum_height)

        if restore_geometry is not None:
            self.setGeometry(restore_geometry)
        self._set_sidebar_collapsed(restore_sidebar, restore_size=False)

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
        max_width = max(self._SIDEBAR_MIN_WIDTH, self.width() - 220)
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
        self.reset_view_btn.setVisible(visible)
        self.sidebar_toggle_btn.setVisible(visible)

    def _enter_compact_mode(self) -> None:
        if self._compact_state_active or self.isMaximized():
            return
        self._compact_state_active = True
        self._compact_restore_geometry = self.geometry()
        self._compact_restore_sidebar_collapsed = self._sidebar_collapsed
        self.setMinimumHeight(theme.COMPACT_ALERT_HEIGHT + self._window_margin * 2)

        current = self.geometry()
        compact_height = theme.COMPACT_ALERT_HEIGHT + self._window_margin * 2
        self.setGeometry(current.x(), current.y(), current.width(), compact_height)

    def _exit_compact_mode(self) -> None:
        if not self._compact_state_active:
            return
        self._restore_from_compact_mode()

    def _apply_state_feedback(self, state: TrackState) -> None:
        if self._is_pause_mode():
            self._restore_lock_state_after_lost()
            self._set_alert_mode(False)
            self._set_header_action_visibility(True)
            self.state_hint_label.setText("暂停定位")
            self.state_hint_label.setStyleSheet("")
            self._exit_compact_mode()
            return

        if state == TrackState.LOCKED:
            self._restore_lock_state_after_lost()
            self._set_alert_mode(False)
            self._set_header_action_visibility(True)
            self.state_hint_label.setText("定位稳定")
            self.state_hint_label.setStyleSheet("")
            self._exit_compact_mode()
            return

        if state == TrackState.SEARCHING:
            self._jump_anomaly_count = 0
            self._exit_lost_mode()
            self._set_alert_mode(False)
            self._set_header_action_visibility(True)
            self.state_hint_label.setText("正在搜索目标，请稍候…")
            self.state_hint_label.setStyleSheet("")
            self._exit_compact_mode()
            return

        if state == TrackState.INERTIAL:
            self._restore_lock_state_after_lost()
            self._set_alert_mode(False)
            self._set_header_action_visibility(True)
            self.state_hint_label.setVisible(True)
            self.state_hint_label.setText("定位暂时不稳定，沿用上一帧位置。")
            self.state_hint_label.setStyleSheet("")
            self._exit_compact_mode()
            return

        self._enter_lost_mode()
        self._set_alert_mode(True, "目标丢失，正在持续尝试重新定位。", allow_terminate=True)
        self._set_header_action_visibility(False)
        self._enter_compact_mode()

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

        if self.isMaximized() or self._compact_state_active:
            return

        if self._sidebar_collapsed:
            self._collapsed_size_memory = (self.width(), self.height())
        else:
            if self.width() >= theme.SIDEBAR_MIN_EXPANDED_W:
                self._expanded_size_memory = (self.width(), self.height())
            elif self._expanded_size_memory is None:
                self._expanded_size_memory = (
                    theme.SIDEBAR_MIN_EXPANDED_W,
                    max(theme.SIDEBAR_MIN_EXPANDED_H, self.height()),
                )
            else:
                self._expanded_size_memory = (
                    self._expanded_size_memory[0],
                    max(self._expanded_size_memory[1], self.height()),
                )
            if self.width() < theme.SIDEBAR_MIN_EXPANDED_W:
                self._set_sidebar_collapsed(True, restore_size=False)

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_flags(self)

    def closeEvent(self, event):
        self._running = False
        self._stop_hotkey_listener()
        self.route_mgr.save_progress()
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
        if self._lost_mode_active:
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
        self._resume_tracking_attempts()
        self.tracker.set_anchor(x, y)
        self.map_view.preview_relocate(x, y, TrackState.SEARCHING)
        self.coord_label.setText(f"{x} , {y}")
        self._last_player_xy = (x, y)
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
