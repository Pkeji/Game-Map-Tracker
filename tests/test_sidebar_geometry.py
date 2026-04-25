import unittest
from enum import Enum

from PySide6.QtCore import QMargins, QRect

from ui_island.controllers.interaction_controller import InteractionController
from ui_island.controllers.window_mode_controller import WindowModeController


class _Mode(Enum):
    PAUSED = "paused"
    TRACKING_STABLE = "tracking_stable"
    TRACKING_INERTIAL = "tracking_inertial"
    TRACKING_LOST = "tracking_lost"
    MAXIMIZED = "maximized"


class _FakeLayout:
    def __init__(self, margins: QMargins, spacing: int = 0) -> None:
        self._margins = margins
        self._spacing = spacing
        self.widgets: list[object] = []

    def contentsMargins(self) -> QMargins:
        return self._margins

    def spacing(self) -> int:
        return self._spacing

    def indexOf(self, widget) -> int:
        try:
            return self.widgets.index(widget)
        except ValueError:
            return -1

    def addWidget(self, widget, stretch: int = 0) -> None:
        if widget not in self.widgets:
            self.widgets.append(widget)

    def removeWidget(self, widget) -> None:
        if widget in self.widgets:
            self.widgets.remove(widget)

    def setStretch(self, _index: int, _stretch: int) -> None:
        pass


class _FakeWidget:
    def __init__(self, layout: _FakeLayout | None = None, minimum_width: int = 0) -> None:
        self._layout = layout
        self._minimum_width = minimum_width
        self.visible: bool | None = None
        self.minimum_width: int | None = None
        self.maximum_width: int | None = None
        self.geometry = QRect()
        self.parent = None
        self.raised = False

    def layout(self) -> _FakeLayout | None:
        return self._layout

    def minimumWidth(self) -> int:
        return self._minimum_width

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def isVisible(self) -> bool:
        return bool(self.visible)

    def setMinimumWidth(self, width: int) -> None:
        self.minimum_width = int(width)

    def setMaximumWidth(self, width: int) -> None:
        self.maximum_width = int(width)

    def setParent(self, parent) -> None:
        self.parent = parent

    def rect(self) -> QRect:
        return QRect(0, 0, 420, 360)

    def setGeometry(self, x: int, y: int, width: int, height: int) -> None:
        self.geometry = QRect(x, y, width, height)

    def raise_(self) -> None:
        self.raised = True


class _FakeWindow:
    def __init__(self, geometry: QRect, sidebar_width: int = 220, collapsed: bool = False) -> None:
        self._geometry = QRect(geometry)
        self._mode = _Mode.TRACKING_STABLE
        self._window_margin = 0
        self._SIDEBAR_MIN_WIDTH = 200
        self._normal_minimum_width = 420
        self.minimum_width = self._normal_minimum_width
        self._sidebar_width = sidebar_width
        self._sidebar_collapsed = collapsed
        self._sidebar_expand_restore_geometry = None
        self._sidebar_resize_start_x = 500
        self._sidebar_resize_start_width = sidebar_width
        self._applying_mode = False
        self._preferred_right_edge = None
        self._size_prefs = {_Mode.TRACKING_STABLE: (geometry.width(), geometry.height())}
        self.root = _FakeWidget(_FakeLayout(QMargins(12, 0, 12, 0), spacing=0))
        body_layout = _FakeLayout(QMargins(0, 0, 0, 0), spacing=12)
        self.body_container = _FakeWidget(body_layout)
        self.map_view = _FakeWidget(minimum_width=260)
        self.sidebar_shell = _FakeWidget()
        self.side_scroll = _FakeWidget()
        body_layout.widgets = [self.map_view, self.sidebar_shell]
        self.window_mode_controller = WindowModeController(self)
        self.window_mode_controller.current_screen_available_geometry = lambda: QRect(0, 0, 1200, 800)

    def geometry(self) -> QRect:
        return QRect(self._geometry)

    def setGeometry(self, *args) -> None:
        if len(args) == 1:
            requested = QRect(args[0])
        else:
            requested = QRect(int(args[0]), int(args[1]), int(args[2]), int(args[3]))
        if requested.width() < self.minimum_width:
            requested.setWidth(self.minimum_width)
        self._geometry = requested

    def width(self) -> int:
        return self._geometry.width()

    def height(self) -> int:
        return self._geometry.height()

    def isMaximized(self) -> bool:
        return False

    def setMinimumWidth(self, width: int) -> None:
        self.minimum_width = int(width)

    def _update_header_button_labels(self) -> None:
        pass


class SidebarGeometryTests(unittest.TestCase):
    def test_dragging_sidebar_wider_keeps_tracking_window_geometry(self) -> None:
        window = _FakeWindow(QRect(480, 10, 520, 400), sidebar_width=220, collapsed=False)
        original_geometry = window.geometry()

        InteractionController(window).resize_sidebar(420)

        self.assertEqual(window._sidebar_width, 300)
        self.assertEqual(window.geometry(), original_geometry)
        self.assertEqual(window.sidebar_shell.minimum_width, 300)

    def test_dragging_sidebar_wider_can_exceed_available_tracking_width(self) -> None:
        window = _FakeWindow(QRect(580, 10, 420, 400), sidebar_width=220, collapsed=False)
        original_geometry = window.geometry()

        InteractionController(window).resize_sidebar(120)

        self.assertEqual(window._sidebar_width, 600)
        self.assertEqual(window.geometry(), original_geometry)
        self.assertEqual(window.minimum_width, window._normal_minimum_width)
        self.assertEqual(window.sidebar_shell.minimum_width, 600)

    def test_expand_from_hidden_keeps_narrow_tracking_geometry(self) -> None:
        window = _FakeWindow(QRect(580, 10, 420, 400), sidebar_width=300, collapsed=True)
        controller = window.window_mode_controller
        narrow_geometry = window.geometry()

        controller.set_sidebar_collapsed(False, restore_size=True)

        self.assertFalse(window._sidebar_collapsed)
        self.assertEqual(window._sidebar_width, 300)
        self.assertEqual(window.geometry(), narrow_geometry)
        self.assertIsNone(window._sidebar_expand_restore_geometry)

        controller.set_sidebar_collapsed(True, restore_size=True)

        self.assertTrue(window._sidebar_collapsed)
        self.assertEqual(window.geometry(), narrow_geometry)
        self.assertIsNone(window._sidebar_expand_restore_geometry)

    def test_repeated_sidebar_drags_do_not_move_tracking_window(self) -> None:
        window = _FakeWindow(QRect(580, 10, 420, 400), sidebar_width=300, collapsed=False)
        controller = window.window_mode_controller
        original_geometry = window.geometry()

        for global_x in (580, 420, 560, 440, 580):
            window._sidebar_resize_start_width = window._sidebar_width
            window._sidebar_resize_start_x = 500
            InteractionController(window).resize_sidebar(global_x)
            self.assertEqual(window.geometry(), original_geometry)

    def test_tracking_sidebar_does_not_raise_window_minimum_width(self) -> None:
        window = _FakeWindow(QRect(580, 10, 420, 400), sidebar_width=600, collapsed=False)

        window.window_mode_controller.apply_sidebar_state()

        self.assertEqual(window.minimum_width, window._normal_minimum_width)

    def test_paused_sidebar_still_uses_expanded_minimum_width(self) -> None:
        window = _FakeWindow(QRect(580, 10, 420, 400), sidebar_width=300, collapsed=False)
        window._mode = _Mode.PAUSED

        window.window_mode_controller.apply_sidebar_state()

        self.assertEqual(window.minimum_width, window.window_mode_controller.width_for_sidebar_width(300))


if __name__ == "__main__":
    unittest.main()
