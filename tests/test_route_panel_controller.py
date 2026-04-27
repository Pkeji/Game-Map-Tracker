import unittest
from enum import Enum
from unittest.mock import patch

from ui_island.controllers.route_panel_controller import RoutePanelController
from ui_island.state import RouteDrawingState


class _Mode(Enum):
    PAUSED = "paused"
    MAXIMIZED = "maximized"
    TRACKING_STABLE = "tracking_stable"


class _FakeSearchInput:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class _FakeSection:
    def __init__(self) -> None:
        self.visible: bool | None = None
        self.force_open: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def set_force_open(self, force_open: bool) -> None:
        self.force_open = bool(force_open)


class _FakeRouteItem:
    def __init__(self) -> None:
        self.visible: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakeMapView:
    def __init__(self) -> None:
        self.focus_calls: list[tuple[int, int]] = []

    def focus_map_position(self, x: int, y: int) -> None:
        self.focus_calls.append((x, y))


class _FakeRouteManager:
    def __init__(self, routes: dict[str, dict] | None = None) -> None:
        self.routes = routes or {}

    def route_for_id(self, route_id: str) -> dict | None:
        return self.routes.get(route_id)

    def route_name_for_id(self, route_id: str) -> str:
        route = self.routes.get(route_id)
        return str(route.get("display_name") or route_id) if route is not None else ""


class _FakeWindow:
    def __init__(self, search_text: str = "") -> None:
        self.search_input = _FakeSearchInput(search_text)
        self._route_sections: dict[str, _FakeSection] = {}
        self._route_widgets_by_category: dict[str, list[tuple[str, str, _FakeRouteItem]]] = {}
        self.recent_refreshed = False
        self._mode = _Mode.PAUSED
        self.route_mgr = _FakeRouteManager()
        self.map_view = _FakeMapView()
        self.relocate_calls: list[tuple[int, int]] = []

    def _on_relocate(self, x: int, y: int) -> None:
        self.relocate_calls.append((x, y))


class RoutePanelFilterTests(unittest.TestCase):
    def _controller_for(self, window: _FakeWindow) -> RoutePanelController:
        controller = RoutePanelController.__new__(RoutePanelController)
        controller.window = window
        controller.refresh_recent_routes = lambda: setattr(window, "recent_refreshed", True)
        controller.confirm_exit_route_drawing = lambda: True
        return controller

    def test_empty_category_stays_visible_without_search_term(self) -> None:
        window = _FakeWindow("")
        section = _FakeSection()
        window._route_sections["空分类"] = section
        window._route_widgets_by_category["空分类"] = []

        self._controller_for(window).apply_route_filter()

        self.assertTrue(section.visible)
        self.assertFalse(section.force_open)
        self.assertTrue(window.recent_refreshed)

    def test_empty_category_hides_when_searching(self) -> None:
        window = _FakeWindow("采集")
        section = _FakeSection()
        window._route_sections["空分类"] = section
        window._route_widgets_by_category["空分类"] = []

        self._controller_for(window).apply_route_filter()

        self.assertFalse(section.visible)
        self.assertFalse(section.force_open)

    def test_matching_category_shows_and_force_opens_when_searching(self) -> None:
        window = _FakeWindow("矿")
        section = _FakeSection()
        route_item = _FakeRouteItem()
        window._route_sections["资源"] = section
        window._route_widgets_by_category["资源"] = [("route-1", "矿物采集", route_item)]

        self._controller_for(window).apply_route_filter()

        self.assertTrue(route_item.visible)
        self.assertTrue(section.visible)
        self.assertTrue(section.force_open)

    def test_route_drawing_loop_change_marks_state_dirty(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="采集",
            name="路线",
            points=[{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}],
            loop=False,
        )
        controller = self._controller_for(window)

        controller._mark_drawing_dirty()
        self.assertFalse(window.route_drawing_state.dirty)

        window.route_drawing_state.loop = True
        controller._mark_drawing_dirty()

        self.assertTrue(window.route_drawing_state.dirty)

    def test_drawing_point_node_type_change_marks_dirty_and_undo_restores(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2, "node_type": "collect"}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.set_drawing_point_node_type(0, "teleport"))
        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "teleport")
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "collect")
        self.assertFalse(window.route_drawing_state.dirty)

    def test_drawing_point_node_type_defaults_missing_type_to_collect(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.set_drawing_point_node_type(0, ""))
        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "collect")
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        self.assertNotIn("node_type", window.route_drawing_state.draft_points[0])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_jump_to_route_node_paused_relocates_to_first_valid_node(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.PAUSED
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": "bad", "y": 2},
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": False},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast"):
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.relocate_calls, [(10, 20)])
        self.assertEqual(window.map_view.focus_calls, [])

    def test_jump_to_route_node_navigation_focuses_first_unvisited_without_relocating(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": False},
                    {"x": 50, "y": 60, "visited": False},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast"):
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.map_view.focus_calls, [(30, 40)])
        self.assertEqual(window.relocate_calls, [])

    def test_jump_to_route_node_navigation_completed_falls_back_to_first_node(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": True},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast") as toast_mock:
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.map_view.focus_calls, [(10, 20)])
        self.assertEqual(window.relocate_calls, [])
        self.assertIn("1", toast_mock.call_args.args[1])

    def test_jump_to_route_node_empty_route_shows_info_without_moving(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({"route-1": {"points": [{"x": "bad"}]}})
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.styled_info") as info_mock:
            controller.jump_to_route_node("route-1")

        self.assertTrue(info_mock.called)
        self.assertEqual(window.map_view.focus_calls, [])
        self.assertEqual(window.relocate_calls, [])


if __name__ == "__main__":
    unittest.main()
