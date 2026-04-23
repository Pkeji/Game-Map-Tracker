"""Centralized access to config-backed settings."""

from __future__ import annotations

import config


class SettingsGateway:
    def save(self, values: dict) -> None:
        config.save_config(values)

    def get_minimap(self):
        return config.MINIMAP

    def get_window_geometry(self):
        return config.WINDOW_GEOMETRY

    def parse_window_geometry(self, raw):
        return config.parse_window_geometry(raw)

    def get_sidebar_collapsed(self):
        return config.SIDEBAR_COLLAPSED

    def get_sidebar_width(self):
        return config.SIDEBAR_WIDTH

    def get_paused_sidebar_width(self):
        return getattr(config, "PAUSED_SIDEBAR_WIDTH", None)

    def get_locked_view_size(self):
        return config.LOCKED_VIEW_SIZE

    def get_paused_view_size(self):
        return getattr(config, "PAUSED_VIEW_SIZE", None)

    def get_route_recent_limit(self) -> int:
        return max(0, int(getattr(config, "ROUTE_RECENT_LIMIT", 5) or 0))

    def get_tracker_refresh_rate(self, tracker) -> int:
        return int(config.AI_REFRESH_RATE if hasattr(tracker, "engine") else config.SIFT_REFRESH_RATE)
