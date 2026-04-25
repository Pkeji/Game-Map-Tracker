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
        recent_route_ids: list[str] = []
        seen: set[str] = set()
        for item in data:
            route_id = self._route_mgr.resolve_route_id(item)
            if route_id is None or route_id in seen:
                continue
            seen.add(route_id)
            recent_route_ids.append(route_id)
        return recent_route_ids

    def save(self, recent_route_ids: list[str]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(recent_route_ids, handle, indent=2, ensure_ascii=False)
        except Exception:
            pass
