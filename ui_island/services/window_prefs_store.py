"""Persistence helper for window geometry and size preferences."""

from __future__ import annotations

from .settings_gateway import SettingsGateway


class WindowPrefsStore:
    def __init__(self, gateway: SettingsGateway) -> None:
        self._gateway = gateway

    def load_window_geometry(self):
        return self._gateway.parse_window_geometry(self._gateway.get_window_geometry())

    def load_sidebar_collapsed(self):
        return self._gateway.get_sidebar_collapsed()

    def load_sidebar_width(self):
        return self._gateway.get_sidebar_width()

    def load_paused_sidebar_width(self):
        return self._gateway.get_paused_sidebar_width()

    def load_locked_view_size(self):
        return self._gateway.get_locked_view_size()

    def load_paused_view_size(self):
        return self._gateway.get_paused_view_size()

    def load_route_section_expanded(self):
        return self._gateway.get_route_section_expanded()

    def save_route_section_expanded(self, expanded: dict[str, bool]) -> None:
        self._gateway.save({"ROUTE_SECTION_EXPANDED": expanded})

    def save_payload(self, payload: dict) -> None:
        self._gateway.save(payload)
