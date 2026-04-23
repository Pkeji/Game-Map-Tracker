"""Persistence helper for recent route selections."""

from __future__ import annotations

import json
import os

from route_manager import RouteManager


class RecentRoutesStore:
    def __init__(self, route_mgr: RouteManager) -> None:
        self._route_mgr = route_mgr

    @property
    def path(self) -> str:
        return os.path.join(self._route_mgr.base_folder, "recent_routes.json")

    def load(self) -> list[str]:
        path = self.path
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        known_routes = {
            route.get("display_name")
            for routes in self._route_mgr.route_groups.values()
            for route in routes
        }
        return [name for name in data if isinstance(name, str) and name in known_routes]

    def save(self, recent_route_names: list[str]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(recent_route_names, handle, indent=2, ensure_ascii=False)
        except Exception:
            pass
