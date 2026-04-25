import unittest

from ui_island.controllers.route_panel_controller import RoutePanelController


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


class _FakeWindow:
    def __init__(self, search_text: str = "") -> None:
        self.search_input = _FakeSearchInput(search_text)
        self._route_sections: dict[str, _FakeSection] = {}
        self._route_widgets_by_category: dict[str, list[tuple[str, str, _FakeRouteItem]]] = {}
        self.recent_refreshed = False


class RoutePanelFilterTests(unittest.TestCase):
    def _controller_for(self, window: _FakeWindow) -> RoutePanelController:
        controller = RoutePanelController.__new__(RoutePanelController)
        controller.window = window
        controller.refresh_recent_routes = lambda: setattr(window, "recent_refreshed", True)
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


if __name__ == "__main__":
    unittest.main()
