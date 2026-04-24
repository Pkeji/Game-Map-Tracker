"""Top-of-screen island overlay with interactive map and route tools."""

from __future__ import annotations

import sys
import threading
from collections import deque
from enum import Enum

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

from base import BaseTracker, TrackResult, TrackState
from route_manager import RouteManager

from ..design import button_specs, qss, theme
from ..services import RecentRoutesStore, SettingsGateway, WindowPrefsStore
from ..state import HotkeyState, RoutePanelState, TrackingState, WindowLayoutPrefs, WindowModeState
from ..widgets import RestoreIcon
from ..platform.win_overlay import apply_overlay_flags, set_click_through
from ..controllers import HotkeyController, InteractionController, RoutePanelController, TrackingController, WindowModeController
from .window_state_bridge import WindowStateBridgeMixin
from .window_view import build_window_ui


class WindowMode(Enum):
    PAUSED = "paused"
    TRACKING_STABLE = "tracking_stable"
    TRACKING_INERTIAL = "tracking_inertial"
    TRACKING_LOST = "tracking_lost"
    MAXIMIZED = "maximized"


_STABLE_FAMILY = {WindowMode.TRACKING_STABLE, WindowMode.TRACKING_INERTIAL}


class IslandWindow(WindowStateBridgeMixin, QWidget):
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
        qss.ensure_tooltip_style()
        self.tracker = tracker
        self.route_mgr = route_mgr
        self.settings_gateway = SettingsGateway()
        self.window_prefs_store = WindowPrefsStore(self.settings_gateway)
        self.recent_routes_store = RecentRoutesStore(self.route_mgr)
        self.window_mode_state = WindowModeState()
        self.window_layout_prefs = WindowLayoutPrefs()
        self.route_panel_state = RoutePanelState()
        self.tracking_state = TrackingState()
        self.hotkey_state = HotkeyState()
        self.route_panel_controller = RoutePanelController(self)
        self.window_mode_controller = WindowModeController(self)
        self.tracking_controller = TrackingController(self)
        self.interaction_controller = InteractionController(self)
        self.hotkey_controller = HotkeyController(self)

        self.tracking_state.locked = False
        self.tracking_state.running = True
        self.tracking_state.latencies = deque(maxlen=30)
        self.tracking_state.last_result = None
        self.tracking_state.last_player_xy = None
        self.tracking_state.latest_minimap = None

        self._is_windows = sys.platform.startswith("win")
        self._window_margin = 0 if self._is_windows else 10
        self._shadow_enabled = not self._is_windows

        self._recent_limit = self.settings_gateway.get_route_recent_limit()
        self.route_panel_state.recent_route_names = self.recent_routes_store.load()
        self.route_panel_state.route_checkboxes = {}
        self._tracked_route_progress_signature: tuple[tuple[str, bool], ...] = ()
        self.route_panel_state.route_widgets_by_category = {}
        self.route_panel_state.route_sections = {}
        self.route_panel_state.route_section_expanded = self.window_prefs_store.load_route_section_expanded()
        self.route_panel_state.active_route_rename_item = None
        self.route_panel_state.adding_category = False
        self.route_panel_state.add_category_row = None
        self.route_panel_state.add_category_input = None
        self.route_panel_state.add_category_confirm_btn = None
        self.route_panel_state.add_category_cancel_btn = None

        saved_collapsed = self.window_prefs_store.load_sidebar_collapsed()
        saved_sidebar_w = self.window_prefs_store.load_sidebar_width()
        self.window_layout_prefs.sidebar_collapsed = bool(saved_collapsed) if saved_collapsed is not None else False
        try:
            tracking_sidebar_width = max(120, int(saved_sidebar_w)) if saved_sidebar_w is not None else 320
        except (TypeError, ValueError):
            tracking_sidebar_width = 320
        saved_paused_sidebar_w = self.window_prefs_store.load_paused_sidebar_width()
        try:
            self.window_layout_prefs.paused_sidebar_width = (
                max(120, int(saved_paused_sidebar_w))
                if saved_paused_sidebar_w is not None
                else tracking_sidebar_width
            )
        except (TypeError, ValueError):
            self.window_layout_prefs.paused_sidebar_width = tracking_sidebar_width
        self.window_layout_prefs.sidebar_width = self.window_layout_prefs.paused_sidebar_width

        self.window_layout_prefs.normal_minimum_width = theme.WINDOW_MIN_W + self._window_margin * 2
        self.window_layout_prefs.normal_minimum_height = max(
            theme.WINDOW_MIN_H,
            theme.TRACKING_WINDOW_MIN_H,
        ) + self._window_margin * 2
        self.tracking_state.tracking_attempts_paused = False
        self.tracking_state.tracking_paused_state = TrackState.SEARCHING
        self.tracking_state.jump_anomaly_count = 0
        self.tracking_state.preferred_locked = False
        self.tracking_state.lock_state_before_lost = None
        self.tracking_state.restore_lock_after_relocate = None
        self.tracking_state.tracking_bootstrap_pending = False

        self._mode = WindowMode.PAUSED
        self.window_mode_state.mode_before_max = None
        self.window_layout_prefs.geometry_before_max = None
        self.window_mode_state.applying_mode = False
        self.window_mode_state.preferred_right_edge = None
        self.window_layout_prefs.sidebar_collapsed_before_pause = bool(self._sidebar_collapsed)
        self.window_layout_prefs.sidebar_width_before_pause = tracking_sidebar_width
        self.window_layout_prefs.sidebar_collapsed_before_max = None
        self.window_layout_prefs.sidebar_width_before_max = None
        self.window_layout_prefs.sidebar_expand_restore_geometry = None
        paused_w = theme.EXPANDED_W + self._window_margin * 2
        paused_h = theme.EXPANDED_H + self._window_margin * 2
        self.window_layout_prefs.size_prefs = {
            WindowMode.PAUSED: (paused_w, paused_h),
        }

        saved_stable = self.window_prefs_store.load_locked_view_size()
        if isinstance(saved_stable, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_stable["width"]))
                h = max(self._normal_minimum_height, int(saved_stable["height"]))
                self.window_layout_prefs.size_prefs[WindowMode.TRACKING_STABLE] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass
        saved_paused = self.window_prefs_store.load_paused_view_size()
        if isinstance(saved_paused, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_paused["width"]))
                h = max(self._normal_minimum_height, int(saved_paused["height"]))
                self.window_layout_prefs.size_prefs[WindowMode.PAUSED] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass

        self._stable_size_save_timer = QTimer(self)
        self._stable_size_save_timer.setSingleShot(True)
        self._stable_size_save_timer.setInterval(300)
        self._stable_size_save_timer.timeout.connect(self.window_mode_controller.flush_stable_size_to_config)
        self._paused_size_save_timer = QTimer(self)
        self._paused_size_save_timer.setSingleShot(True)
        self._paused_size_save_timer.setInterval(300)
        self._paused_size_save_timer.timeout.connect(self.window_mode_controller.flush_paused_size_to_config)

        self._move_dragging = False
        self._move_drag_offset = None
        self._edge_cursor_active = False
        self._system_resize_edges = Qt.Edges()
        self._sidebar_resizing = False
        self._sidebar_resize_start_x = 0
        self._sidebar_resize_start_width = self._sidebar_width
        self._header_buttons_icon_only = False
        self._mini_icon = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)

        build_window_ui(self)
        self.window_mode_controller.sync_normal_minimum_height()
        self.window_mode_controller.sync_compact_minimum_height()
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)
        self.interaction_controller.install_resize_filters(self.root)
        self.installEventFilter(self)
        self.window_mode_controller.restore_or_center()
        self.window_mode_controller.enter_mode(WindowMode.PAUSED)
        QTimer.singleShot(0, self._paint_default_map)

        self._toggle_lock_requested.connect(self.toggle_lock, Qt.QueuedConnection)
        self._frame_ready.connect(self._on_frame)

        self._minimap_region = self.settings_gateway.get_minimap()
        self.hotkey_controller.start_listener()

        self._thread = threading.Thread(target=self.tracking_controller.tracker_loop, daemon=True)
        self._thread.start()

    def _handle_manual_map_navigation(self) -> None:
        self.map_view.set_center_locked(False)

    def _reset_map_view(self) -> None:
        self.map_view.reset_view()

    def _paint_default_map(self) -> None:
        cx = self.tracker.map_width // 2
        cy = self.tracker.map_height // 2
        self.map_view.preview_relocate(cx, cy, TrackState.SEARCHING)

    def _open_settings(self) -> None:
        from ..dialogs.settings_dialog import open_settings_dialog

        open_settings_dialog(self, on_applied=self._on_settings_applied)

    def _on_settings_applied(self) -> None:
        self._minimap_region = self.settings_gateway.get_minimap()

    def _collapse_to_icon(self) -> None:
        if self._mini_icon is not None:
            return
        geom = self.frameGeometry()
        anchor = geom.topLeft()
        self._mini_icon = RestoreIcon(self, self._restore_from_icon, self._close_app_from_icon)
        last = getattr(self, "_last_result", None)
        if last is not None:
            self._mini_icon.set_state(last.state)
        self._mini_icon.set_coord(self.coord_label.text())
        self._mini_icon.place_at(anchor)
        self._mini_icon.show()
        self.hide()

    def _restore_from_icon(self) -> None:
        if self._mini_icon is not None:
            self._mini_icon.close()
            self._mini_icon = None
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _close_app_from_icon(self) -> None:
        if self._mini_icon is not None:
            self._mini_icon.close()
            self._mini_icon = None
        self._quit_entire_app()

    def _quit_entire_app(self) -> None:
        self._running = False
        self.hotkey_controller.stop_listener()
        try:
            self.route_mgr.save_progress()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is not self:
                    widget.close()
            app.quit()
        self.close()

    def _update_window_controls(self) -> None:
        self.max_btn.setText("❐" if self.isMaximized() else "▢")
        self._update_header_button_labels()
        self._update_lock_button_visibility()

    def _set_header_button_presentation(
        self,
        button,
        *,
        text: str,
        icon_text: str,
        tooltip: str,
        compact_width: int = 34,
    ) -> None:
        button_specs.apply_header_button_presentation(
            button,
            icon_only=self._header_buttons_icon_only,
            spec=button_specs.HeaderButtonSpec(
                text=text,
                icon_text=icon_text,
                tooltip=tooltip,
                compact_width=compact_width,
            ),
        )

    def _update_header_button_labels(self) -> None:
        if self.window_mode_controller.is_pause_mode():
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
        is_paused = self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED)
        action_text = "开始导航" if is_paused else "重定位"
        action_icon = "导" if is_paused else "⌖"

        specs = [
            {"button": self.relocate_btn, "text": action_text, "icon_text": action_icon, "tooltip": action_text, "compact_width": 34},
            {"button": self.reset_view_btn, "text": "重置视图", "icon_text": "↺", "tooltip": "重置视图", "compact_width": 34},
            {"button": self.sidebar_toggle_btn, "text": sidebar_text, "icon_text": sidebar_icon, "tooltip": sidebar_text, "compact_width": 34},
            {"button": self.terminate_nav_btn, "text": "终止导航", "icon_text": "止", "tooltip": "终止导航", "compact_width": 34},
            {"button": self.lock_btn, "text": lock_text, "icon_text": lock_icon, "tooltip": lock_text, "compact_width": 34},
        ]

        self._header_buttons_icon_only = self.width() < self._HEADER_ICON_SWITCH_WIDTH
        for spec in specs:
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

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            target_area = self.interaction_controller.nested_sidebar_scroll_area(
                watched if isinstance(watched, QWidget) else None
            )
            if target_area is not None:
                self.interaction_controller.consume_inner_scroll(target_area, event)
                return True

        if (
            self._active_route_rename_item is not None
            and event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
        ):
            local_pos = self._active_route_rename_item.mapFromGlobal(event.globalPosition().toPoint())
            if not self._active_route_rename_item.rect().contains(local_pos):
                self.route_panel_controller.cancel_active_route_rename()

        if (
            self._adding_category
            and event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
            and self._add_category_row is not None
        ):
            local_pos = self._add_category_row.mapFromGlobal(event.globalPosition().toPoint())
            if not self._add_category_row.rect().contains(local_pos):
                self.route_panel_controller.cancel_add_category()

        if event.type() == QEvent.MouseButtonPress and hasattr(event, "globalPosition") and event.button() == Qt.LeftButton:
            if self.interaction_controller.sidebar_resize_hit(event.globalPosition().toPoint()):
                self._sidebar_resizing = True
                self._sidebar_resize_start_x = event.globalPosition().toPoint().x()
                self._sidebar_resize_start_width = self._sidebar_width
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return True

        if event.type() == QEvent.MouseMove and hasattr(event, "globalPosition"):
            if self._sidebar_resizing:
                self.interaction_controller.resize_sidebar(event.globalPosition().toPoint().x())
                return True
            if self.interaction_controller.sidebar_resize_hit(event.globalPosition().toPoint()):
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return False

        if event.type() == QEvent.MouseButtonRelease and self._sidebar_resizing:
            self._sidebar_resizing = False
            return True

        if event.type() == QEvent.MouseButtonRelease and hasattr(event, "button") and event.button() == Qt.LeftButton:
            self._system_resize_edges = Qt.Edges()

        if watched is self.title_drag_area:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and not self.isMaximized():
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
            self.interaction_controller.update_resize_cursor(event.globalPosition().toPoint())
        elif event.type() == QEvent.Leave and not self._move_dragging and self._edge_cursor_active:
            self.unsetCursor()
            self._edge_cursor_active = False

        if (
            event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
            and not self.isMaximized()
        ):
            edges = self.interaction_controller.resize_edges_at(event.globalPosition().toPoint())
            if edges and self.windowHandle() is not None and self.windowHandle().startSystemResize(edges):
                self._system_resize_edges = edges
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

        if self.isMaximized() or self._applying_mode:
            return

        if self._mode in _STABLE_FAMILY and not self._tracking_bootstrap_pending:
            self._size_prefs[WindowMode.TRACKING_STABLE] = (self.width(), self.height())
            self._stable_size_save_timer.start()
        elif self._mode == WindowMode.TRACKING_LOST:
            stable_width, stable_height = self._size_prefs.get(
                WindowMode.TRACKING_STABLE,
                self._size_prefs[WindowMode.PAUSED],
            )
            if self.width() != stable_width:
                self._size_prefs[WindowMode.TRACKING_STABLE] = (self.width(), stable_height)
                self._stable_size_save_timer.start()
        elif self._mode == WindowMode.PAUSED:
            self._size_prefs[WindowMode.PAUSED] = (self.width(), self.height())
            self._paused_size_save_timer.start()

        if self._system_resize_edges & Qt.RightEdge and not (self._system_resize_edges & Qt.LeftEdge):
            self._preferred_right_edge = self.x() + self.width()

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._applying_mode and not self.isMaximized():
            self._preferred_right_edge = self.x() + self.width()

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_flags(self)

    def closeEvent(self, event):
        self._running = False
        self.hotkey_controller.stop_listener()
        self.route_panel_controller.save_route_section_expanded()
        self.route_mgr.save_visibility()
        self.route_mgr.save_progress()
        self.window_mode_controller.save_window_geometry()
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is not self:
                    widget.close()
            app.quit()
        super().closeEvent(event)

    def toggle_lock(self) -> None:
        if not self._can_toggle_lock():
            return
        self._preferred_locked = not self._locked
        self._set_locked_state(self._preferred_locked)

    def _prompt_relocate(self) -> None:
        if self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED):
            self.tracking_controller.start_navigation()
            return

        self._restore_lock_after_relocate = self._preferred_locked
        if self._mode == WindowMode.TRACKING_LOST:
            self.tracking_controller.exit_lost_mode()
        self.tracking_controller.resume_tracking_attempts()
        if self._mode == WindowMode.TRACKING_LOST:
            self.tracking_controller.set_alert_mode(True, "正在搜索目标，请稍候…", allow_terminate=True)
            self.tracking_controller.set_header_action_visibility(False)
            self.state_hint_label.setVisible(False)
        else:
            self.setMinimumHeight(self._normal_minimum_height)
            self.tracking_controller.set_alert_mode(False)
            self.tracking_controller.set_header_action_visibility(True)
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
        self.tracker.set_anchor(x, y)
        self.map_view.preview_relocate(x, y, TrackState.SEARCHING)
        self.coord_label.setText(f"{x} , {y}")
        self._last_player_xy = (x, y)

        if self._mode == WindowMode.PAUSED:
            return

        self.tracking_controller.resume_tracking_attempts()
        if self._restore_lock_after_relocate is not None:
            self._set_locked_state(self._restore_lock_after_relocate)
            self._restore_lock_after_relocate = None
            self._update_lock_button_visibility()
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, x=x, y=y, latency_ms=0.0))

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
                    self.tracking_controller.clear_tracker_anchor()
                    self._last_player_xy = None
                    state = TrackState.LOST
                    result = TrackResult(TrackState.LOST, latency_ms=result.latency_ms)
            else:
                self._jump_anomaly_count = 0
        elif state != TrackState.LOCKED:
            self._jump_anomaly_count = 0

        self._last_result = result
        self.dot.set_state(state)
        mini = self._mini_icon
        if mini is not None:
            mini.set_state(state)
        self.tracking_controller.apply_state_feedback(state)
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
            progress_signature = self.route_panel_controller.build_tracked_route_progress_signature()
            if progress_signature != self._tracked_route_progress_signature:
                self.route_panel_controller.refresh_tracked_routes()
        else:
            coord_text = "-- , --"
            self.coord_label.setText(coord_text)

        if mini is not None:
            mini.set_coord(coord_text)

        self.stat_label.setText(f"{avg_latency:4.0f} ms · {fps:4.1f} fps")
