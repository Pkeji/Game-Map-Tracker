"""Route loading, drawing, persistence, and filesystem operations."""

from __future__ import annotations

import colorsys
import glob
import hashlib
import json
import math
import os
import shutil
import time
from collections import defaultdict
from datetime import datetime
from typing import Iterable

import cv2

_CLOSE_THRESHOLD = 20
_PROGRESS_FILE = "progress.json"
_VISIBILITY_FILE = "selected_routes.json"
_RECENT_FILE = "recent_routes.json"
_INVALID_FILE_NAME_CHARS = set('<>:"/\\|?*')
_ROUTE_ID_SEQ_WIDTH = 2


def _color_for_key(key: str) -> tuple[int, int, int]:
    """Stable fallback color derived from a route key."""
    digest = hashlib.md5(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


def _best_insertion_index(points: list[dict], new_xy: tuple[float, float]) -> int:
    """返回让总路径长度增量最小的插入下标。
    空列表 → 0;单点 → 1(尾部);多点遍历每段边及首尾外插。
    """
    if not points:
        return 0
    if len(points) == 1:
        return 1

    nx, ny = float(new_xy[0]), float(new_xy[1])
    best_index = 0
    best_cost = math.hypot(nx - points[0]["x"], ny - points[0]["y"])

    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        orig = math.hypot(curr["x"] - prev["x"], curr["y"] - prev["y"])
        detour = (
            math.hypot(nx - prev["x"], ny - prev["y"])
            + math.hypot(curr["x"] - nx, curr["y"] - ny)
            - orig
        )
        if detour < best_cost:
            best_cost = detour
            best_index = i

    tail_cost = math.hypot(nx - points[-1]["x"], ny - points[-1]["y"])
    if tail_cost < best_cost:
        best_index = len(points)

    return best_index


class RouteManager:
    def __init__(self, base_folder: str = "routes") -> None:
        self.base_folder = base_folder
        self.categories: list[str] = []
        self.route_groups: dict[str, list[dict]] = {}
        self.visibility: dict[str, bool] = {}
        self._color_cache: dict[str, tuple[int, int, int]] = {}
        self._route_index_by_id: dict[str, dict] = {}
        self._category_by_route_id: dict[str, str] = {}

        self._discover_categories()
        self._ensure_route_ids()
        self._load_all_routes()
        self._assign_route_colors()
        self._load_visibility()
        self._load_progress()

    def color_for(self, key: str) -> tuple[int, int, int]:
        if key not in self._color_cache:
            self._color_cache[key] = _color_for_key(key)
        return self._color_cache[key]

    @staticmethod
    def route_id(route: dict) -> str:
        route_id = route.get("id")
        return route_id if isinstance(route_id, str) else ""

    def iter_routes(self) -> Iterable[tuple[str, dict]]:
        for category in self.categories:
            for route in self.route_groups[category]:
                yield category, route

    def route_for_id(self, route_id: str) -> dict | None:
        if not isinstance(route_id, str):
            return None
        return self._route_index_by_id.get(route_id)

    def category_for_route_id(self, route_id: str) -> str | None:
        if not isinstance(route_id, str):
            return None
        return self._category_by_route_id.get(route_id)

    def summarize_route(self, route_id: str) -> dict | None:
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        if route is None or category is None:
            return None
        return {
            "display_label": route.get("display_name", ""),
            "points_count": len(route.get("points", []) or []),
            "category": category,
        }

    def suggest_insertion_index(self, route_id: str, x: float, y: float) -> int | None:
        route = self.route_for_id(route_id)
        if route is None:
            return None
        return _best_insertion_index(route.get("points", []) or [], (x, y))

    def hit_test_point(
        self,
        map_x: float,
        map_y: float,
        threshold: float,
        route_ids: list[str] | None = None,
    ) -> tuple[str, int] | None:
        """在给定 map 坐标附近查找最近的路线节点。
        route_ids=None 时只在可见路线中查找;threshold 为 map 像素距离上限。
        命中多个时返回距离最近者(相等时取遍历顺序首者)。
        """
        if threshold <= 0:
            return None

        if route_ids is None:
            candidates = [
                (self.route_id(route), route)
                for route in self.visible_routes()
            ]
        else:
            candidates = []
            for rid in route_ids:
                route = self.route_for_id(rid)
                if route is not None:
                    candidates.append((rid, route))

        best: tuple[float, str, int] | None = None
        for rid, route in candidates:
            if not rid:
                continue
            points = route.get("points") or []
            for index, point in enumerate(points):
                try:
                    px = float(point["x"])
                    py = float(point["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                dist = math.hypot(px - map_x, py - map_y)
                if dist > threshold:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, rid, index)

        if best is None:
            return None
        return best[1], best[2]

    def delete_points_from_routes(
        self,
        deletions: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        """从多条路线批量删除指定下标的节点并写回 JSON。
        deletions: route_id -> 待删除 index 列表(重复/越界/非 int 会自动剔除)。
        返回每条路线实际删除成功的 index 列表(升序);失败或无效项返回空 list。
        删除采用从高到低 pop 避免偏移;写盘失败回滚内存状态。
        """
        outcomes: dict[str, list[int]] = {}
        any_success = False

        for route_id, raw_indexes in deletions.items():
            outcomes[route_id] = []
            route = self.route_for_id(route_id)
            category = self.category_for_route_id(route_id)
            if route is None or category is None:
                continue

            points = route.get("points")
            if not points:
                continue

            cleaned: set[int] = set()
            for item in raw_indexes or []:
                if isinstance(item, bool):
                    continue
                if not isinstance(item, int):
                    continue
                if 0 <= item < len(points):
                    cleaned.add(item)
            if not cleaned:
                continue

            descending = sorted(cleaned, reverse=True)
            popped_points: list[dict] = []
            popped_indexes: list[int] = []
            for idx in descending:
                popped_points.append(points.pop(idx))
                popped_indexes.append(idx)

            try:
                self._write_route_file(category, route.get("display_name", ""), route)
            except Exception as e:
                for idx, saved in zip(reversed(popped_indexes), reversed(popped_points)):
                    points.insert(idx, saved)
                print(f"Delete points write failed route_id={route_id}: {e}")
                continue

            outcomes[route_id] = sorted(cleaned)
            any_success = True

        if any_success:
            try:
                self.save_progress()
            except Exception as e:
                print(f"Save progress after delete failed: {e}")

        return outcomes

    def insert_point_into_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str],
        overrides: dict[str, int] | None = None,
    ) -> dict[str, int | None]:
        """为每个 route_id 在最佳位置插入 (x, y) 节点并写回 JSON。
        overrides: route_id -> 强制 index(0-based),超出范围会 clamp。
        返回每个 route_id 实际插入的 index;失败为 None。
        """
        overrides = overrides or {}
        outcomes: dict[str, int | None] = {}
        any_success = False

        for route_id in route_ids:
            route = self.route_for_id(route_id)
            category = self.category_for_route_id(route_id)
            if route is None or category is None:
                outcomes[route_id] = None
                continue

            points = route.get("points")
            if points is None:
                points = []
                route["points"] = points

            if route_id in overrides:
                raw = overrides[route_id]
                try:
                    index = int(raw)
                except (TypeError, ValueError):
                    index = _best_insertion_index(points, (x, y))
                index = max(0, min(len(points), index))
            else:
                index = _best_insertion_index(points, (x, y))

            new_point = {"x": int(x), "y": int(y), "visited": False}
            points.insert(index, new_point)

            try:
                self._write_route_file(category, route.get("display_name", ""), route)
            except Exception as e:
                points.pop(index)
                print(f"Insert point write failed route_id={route_id}: {e}")
                outcomes[route_id] = None
                continue

            outcomes[route_id] = index
            any_success = True

        if any_success:
            try:
                self.save_progress()
            except Exception as e:
                print(f"Save progress after insert failed: {e}")

        return outcomes

    def route_name_for_id(self, route_id: str) -> str:
        route = self.route_for_id(route_id)
        if route is None:
            return ""
        return route.get("display_name", "")

    def resolve_route_id(self, value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        if value in self._route_index_by_id:
            return value

        matches = [
            self.route_id(route)
            for _category, route in self.iter_routes()
            if route.get("display_name") == value
        ]
        matches = [route_id for route_id in matches if route_id]
        if len(matches) == 1:
            return matches[0]
        return None

    def visible_routes(self) -> list[dict]:
        return [
            route
            for _category, route in self.iter_routes()
            if self.visibility.get(self.route_id(route), False)
        ]

    def visible_route_ids(self) -> list[str]:
        return [self.route_id(route) for route in self.visible_routes() if self.route_id(route)]

    def visible_route_names(self) -> list[str]:
        return [route.get("display_name", "") for route in self.visible_routes()]

    def has_progress(self, route_ref: str) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        if route is None:
            return False
        return any(point.get("visited", False) for point in route.get("points", []))

    def reload(self) -> None:
        self.save_visibility()
        self.save_progress()
        self.categories = []
        self.route_groups = {}
        self.visibility = {}
        self._color_cache = {}
        self._route_index_by_id = {}
        self._category_by_route_id = {}
        self._discover_categories()
        self._ensure_route_ids()
        self._load_all_routes()
        self._assign_route_colors()
        self._load_visibility()
        self._load_progress()

    def create_category(self, name: str) -> bool:
        category = name.strip()
        if not self._is_valid_fs_name(category):
            return False
        os.makedirs(os.path.join(self.base_folder, category), exist_ok=True)
        return True

    def rename_category(self, old_name: str, new_name: str) -> bool:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if old_name == new_name:
            return True
        if old_name not in self.categories or not self._is_valid_fs_name(new_name):
            return False

        old_path = self._category_path(old_name)
        new_path = self._category_path(new_name)
        if not os.path.isdir(old_path) or os.path.exists(new_path):
            return False

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            print(f"Rename category failed {old_path} -> {new_path}: {e}")
            return False

        index = self.categories.index(old_name)
        self.categories[index] = new_name
        moved_routes = self.route_groups.pop(old_name, [])
        self.route_groups[new_name] = moved_routes
        for route in moved_routes:
            route_id = self.route_id(route)
            if route_id:
                self._category_by_route_id[route_id] = new_name
        return True

    def delete_category(self, name: str) -> bool:
        name = name.strip()
        if name not in self.categories:
            return False

        path = self._category_path(name)
        if not os.path.isdir(path):
            return False

        for route in self.route_groups.get(name, []):
            route_id = self.route_id(route)
            if route_id:
                self.visibility.pop(route_id, None)
                self._color_cache.pop(route_id, None)
                self._route_index_by_id.pop(route_id, None)
                self._category_by_route_id.pop(route_id, None)

        try:
            shutil.rmtree(path)
        except OSError as e:
            print(f"Delete category failed {path}: {e}")
            return False

        self.categories = [category for category in self.categories if category != name]
        self.route_groups.pop(name, None)
        self.save_visibility()
        self.save_progress()
        return True

    def create_route(self, category: str, name: str) -> bool:
        name = name.strip()
        if not self._is_valid_route_name(name):
            return False
        if category not in self.categories:
            return False
        category_dir = self._category_path(category)
        if not os.path.isdir(category_dir):
            return False
        path = self._route_file_path(category, name)
        if os.path.exists(path):
            return False

        payload = {
            "id": self._next_route_id(datetime.now().strftime("%Y%m%d")),
            "name": name,
            "notes": "",
            "loop": False,
            "points": [],
        }
        try:
            self._write_json_file(path, payload)
        except Exception as e:
            print(f"Create route failed {path}: {e}")
            return False
        return True

    def rename_route(self, category: str, old_name: str, new_name: str) -> bool:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not self._is_valid_route_name(new_name):
            return False
        if old_name == new_name:
            return True

        route = self._find_route(category, old_name)
        if route is None:
            return False

        old_path = self._route_file_path(category, old_name)
        new_path = self._route_file_path(category, new_name)
        if not os.path.exists(old_path) or os.path.exists(new_path):
            return False

        old_route_name = route.get("name", old_name)
        try:
            os.replace(old_path, new_path)
            route["display_name"] = new_name
            route["name"] = new_name
            route.setdefault("notes", "")
            self._write_route_file(category, new_name, route)
        except Exception as e:
            route["display_name"] = old_name
            route["name"] = old_route_name
            if os.path.exists(new_path) and not os.path.exists(old_path):
                try:
                    os.replace(new_path, old_path)
                except OSError:
                    pass
            print(f"Rename route failed {old_path} -> {new_path}: {e}")
            return False
        self.save_visibility()
        self.save_progress()
        return True

    def delete_route(self, category: str, name: str) -> bool:
        name = name.strip()
        routes = self.route_groups.get(category)
        if routes is None:
            return False

        route_index = next(
            (index for index, route in enumerate(routes) if route.get("display_name") == name),
            None,
        )
        if route_index is None:
            return False

        route = routes[route_index]
        route_id = self.route_id(route)
        path = self._route_file_path(category, name)
        if os.path.exists(path):
            os.remove(path)

        routes.pop(route_index)
        if route_id:
            self.visibility.pop(route_id, None)
            self._color_cache.pop(route_id, None)
            self._route_index_by_id.pop(route_id, None)
            self._category_by_route_id.pop(route_id, None)
        self.save_visibility()
        self.save_progress()
        return True

    def route_file_path(self, category: str, name: str) -> str:
        return self._route_file_path(category, name)

    def category_path(self, category: str) -> str:
        return self._category_path(category)

    def get_route_notes(self, category: str, name: str) -> str:
        route = self._find_route(category, name)
        if route is None:
            return ""
        notes = route.get("notes", "")
        if notes is None:
            return ""
        return notes if isinstance(notes, str) else str(notes)

    def update_route_notes(self, category: str, name: str, notes: str) -> bool:
        route = self._find_route(category, name)
        if route is None:
            return False

        route["notes"] = notes
        route.setdefault("name", name)
        try:
            self._write_route_file(category, name, route)
        except Exception as e:
            print(f"Save route notes failed {self._route_file_path(category, name)}: {e}")
            return False
        return True

    def draw_on(self, canvas, vx1, vy1, view_size, player_x=None, player_y=None) -> None:
        local_player = None
        if player_x is not None and player_y is not None:
            local_player = (int(player_x - vx1), int(player_y - vy1))

        canvas_height, canvas_width = canvas.shape[:2]

        for _category, route in self.iter_routes():
            route_id = self.route_id(route)
            if not route_id or not self.visibility.get(route_id, False):
                continue

            points = route.get("points", [])
            color = self.color_for(route_id)
            local_points = [(int(point["x"] - vx1), int(point["y"] - vy1)) for point in points]

            for index in range(len(local_points) - 1):
                cv2.line(canvas, local_points[index], local_points[index + 1], color, 2, cv2.LINE_AA)
            if route.get("loop") and len(local_points) > 2:
                cv2.line(canvas, local_points[-1], local_points[0], color, 2, cv2.LINE_AA)

            for index, (local_point, point_data) in enumerate(zip(local_points, points)):
                if not (0 <= local_point[0] <= canvas_width and 0 <= local_point[1] <= canvas_height):
                    continue

                visited = point_data.get("visited", False)
                if not visited and local_player is not None:
                    dist = math.hypot(local_point[0] - local_player[0], local_point[1] - local_player[1])
                    if dist < _CLOSE_THRESHOLD:
                        point_data["visited"] = True
                        visited = True

                if visited:
                    dot_color = (45, 45, 45)
                    border_color = (90, 90, 90)
                    text_color = (100, 100, 100)
                else:
                    dot_color = color
                    border_color = (255, 255, 255)
                    text_color = color

                cv2.circle(canvas, local_point, 5, dot_color, -1)
                cv2.circle(canvas, local_point, 5, border_color, 1, cv2.LINE_AA)

                label = str(index + 1)
                text_x, text_y = local_point[0] + 7, local_point[1] - 4
                cv2.putText(
                    canvas,
                    label,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    canvas,
                    label,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    text_color,
                    1,
                    cv2.LINE_AA,
                )

    def _assign_route_colors(self) -> None:
        all_route_ids = sorted(
            self.route_id(route)
            for _category, route in self.iter_routes()
            if self.route_id(route)
        )
        for index, route_id in enumerate(all_route_ids):
            hue = (index * 0.618033988749895) % 1.0
            sat = 0.82 + (index % 4) * 0.045
            val = 0.92 + (index % 2) * 0.07
            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            self._color_cache[route_id] = (int(b * 255), int(g * 255), int(r * 255))

    def _discover_categories(self) -> None:
        if not os.path.isdir(self.base_folder):
            os.makedirs(self.base_folder, exist_ok=True)

        found: list[str] = []
        for entry in sorted(os.listdir(self.base_folder)):
            full_path = os.path.join(self.base_folder, entry)
            if os.path.isdir(full_path):
                found.append(entry)

        for known in ("植物", "矿物", "地区路线", "其他"):
            if known not in found:
                os.makedirs(os.path.join(self.base_folder, known), exist_ok=True)
                found.append(known)

        self.categories = found
        self.route_groups = {category: [] for category in self.categories}

    def _ensure_route_ids(self) -> None:
        route_files = sorted(
            self._iter_route_files(),
            key=lambda item: (item[2], item[1].casefold()),
        )
        if not route_files:
            return

        used_ids: set[str] = set()
        used_daily_sequences: dict[str, set[int]] = defaultdict(set)
        pending_updates: list[tuple[str, dict, float]] = []

        for _category, path, created_at in route_files:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception as e:
                print(f"Load route for id migration failed {path}: {e}")
                continue

            route_id = data.get("id")
            if self._is_valid_route_id(route_id) and route_id not in used_ids:
                used_ids.add(route_id)
                used_daily_sequences[route_id[:8]].add(int(route_id[8:]))
                continue

            pending_updates.append((path, data, created_at))

        for path, data, created_at in pending_updates:
            route_id = self._allocate_route_id_for_timestamp(created_at, used_ids, used_daily_sequences)
            data["id"] = route_id
            try:
                self._write_json_file(path, data)
            except Exception as e:
                print(f"Write route id migration failed {path}: {e}")

    def _load_all_routes(self) -> None:
        used_ids: set[str] = set()
        used_daily_sequences: dict[str, set[int]] = defaultdict(set)

        for category in self.categories:
            category_path = self._category_path(category)
            for path in glob.glob(os.path.join(category_path, "*.json")):
                try:
                    file_name = os.path.basename(path)
                    if file_name in {_PROGRESS_FILE, _RECENT_FILE, _VISIBILITY_FILE}:
                        continue

                    route_name = os.path.splitext(file_name)[0]
                    with open(path, "r", encoding="utf-8") as handle:
                        data = json.load(handle)

                    route_id = data.get("id")
                    if not self._is_valid_route_id(route_id) or route_id in used_ids:
                        created_at = self._route_file_timestamp(path)
                        route_id = self._allocate_route_id_for_timestamp(created_at, used_ids, used_daily_sequences)
                        data["id"] = route_id
                        self._write_json_file(path, data)
                    else:
                        used_ids.add(route_id)
                        used_daily_sequences[route_id[:8]].add(int(route_id[8:]))

                    data.setdefault("name", route_name)
                    data.setdefault("notes", "")
                    data["display_name"] = route_name
                    for point in data.get("points", []):
                        point["visited"] = False

                    self.route_groups[category].append(data)
                    self._route_index_by_id[route_id] = data
                    self._category_by_route_id[route_id] = category
                    self.visibility[route_id] = False
                except Exception as e:
                    print(f"Load route failed {path}: {e}")

    def _progress_path(self) -> str:
        return os.path.join(self.base_folder, _PROGRESS_FILE)

    def _visibility_path(self) -> str:
        return os.path.join(self.base_folder, _VISIBILITY_FILE)

    def _load_visibility(self) -> None:
        path = self._visibility_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as e:
            print(f"Read route visibility failed: {e}")
            return

        if not isinstance(data, list):
            return

        for item in data:
            route_id = self.resolve_route_id(item)
            if route_id is not None:
                self.visibility[route_id] = True

    def _load_progress(self) -> None:
        path = self._progress_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as e:
            print(f"Read route progress failed: {e}")
            return

        if not isinstance(data, dict):
            return

        for route_ref, visited_indexes in data.items():
            route_id = self.resolve_route_id(route_ref)
            if route_id is None:
                continue
            route = self.route_for_id(route_id)
            if route is None or not isinstance(visited_indexes, list):
                continue
            for index in visited_indexes:
                if 0 <= index < len(route.get("points", [])):
                    route["points"][index]["visited"] = True

    def save_progress(self) -> None:
        data: dict[str, list[int]] = {}
        for _category, route in self.iter_routes():
            route_id = self.route_id(route)
            visited = [
                index
                for index, point in enumerate(route.get("points", []))
                if point.get("visited", False)
            ]
            if route_id and visited:
                data[route_id] = visited
        try:
            with open(self._progress_path(), "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save route progress failed: {e}")

    def reset_progress(self, route_ref: str | None = None) -> None:
        route_id = self.resolve_route_id(route_ref) if route_ref is not None else None
        for _category, route in self.iter_routes():
            if route_id is not None and self.route_id(route) != route_id:
                continue
            for point in route.get("points", []):
                point["visited"] = False
        self.save_progress()

    def save_visibility(self) -> None:
        try:
            with open(self._visibility_path(), "w", encoding="utf-8") as handle:
                json.dump(self.visible_route_ids(), handle, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save route visibility failed: {e}")

    def _route_file_path(self, category: str, name: str) -> str:
        return os.path.join(self.base_folder, category, f"{name}.json")

    def _category_path(self, category: str) -> str:
        return os.path.join(self.base_folder, category)

    def _write_route_file(self, category: str, name: str, route: dict) -> None:
        path = self._route_file_path(category, name)
        route_id = self.route_id(route)
        if not route_id:
            route_id = self._next_route_id()
            route["id"] = route_id
        payload = self._serialize_route(route, name, route_id)
        self._write_json_file(path, payload)

    @staticmethod
    def _serialize_route(route: dict, default_name: str, route_id: str) -> dict:
        payload = {key: value for key, value in route.items() if key != "display_name"}
        payload["id"] = route_id
        payload["name"] = payload.get("name") or default_name
        notes = payload.get("notes", "")
        payload["notes"] = "" if notes is None else (notes if isinstance(notes, str) else str(notes))
        points: list[object] = []
        for point in payload.get("points", []):
            if isinstance(point, dict):
                points.append({key: value for key, value in point.items() if key != "visited"})
            else:
                points.append(point)
        payload["points"] = points
        return payload

    def _find_route(self, category: str, name: str) -> dict | None:
        for route in self.route_groups.get(category, []):
            if route.get("display_name") == name:
                return route
        return None

    def _iter_route_files(self) -> list[tuple[str, str, float]]:
        items: list[tuple[str, str, float]] = []
        for category in self.categories:
            category_path = self._category_path(category)
            for path in glob.glob(os.path.join(category_path, "*.json")):
                if os.path.basename(path) in {_PROGRESS_FILE, _RECENT_FILE, _VISIBILITY_FILE}:
                    continue
                items.append((category, path, self._route_file_timestamp(path)))
        return items

    @staticmethod
    def _route_file_timestamp(path: str) -> float:
        try:
            return os.path.getctime(path)
        except OSError:
            try:
                return os.path.getmtime(path)
            except OSError:
                return time.time()

    @staticmethod
    def _date_key_for_timestamp(timestamp: float) -> str:
        return time.strftime("%Y%m%d", time.localtime(timestamp))

    @staticmethod
    def _format_route_id(date_key: str, sequence: int) -> str:
        return f"{date_key}{sequence:0{_ROUTE_ID_SEQ_WIDTH}d}"

    def _allocate_route_id_for_timestamp(
        self,
        timestamp: float,
        used_ids: set[str],
        used_daily_sequences: dict[str, set[int]],
    ) -> str:
        date_key = self._date_key_for_timestamp(timestamp)
        used_sequences = used_daily_sequences[date_key]
        sequence = 1
        while sequence in used_sequences:
            sequence += 1
        route_id = self._format_route_id(date_key, sequence)
        used_sequences.add(sequence)
        used_ids.add(route_id)
        return route_id

    def _next_route_id(self, date_key: str | None = None) -> str:
        target_date = date_key or datetime.now().strftime("%Y%m%d")
        used_sequences = {
            int(route_id[8:])
            for route_id in self._route_index_by_id
            if route_id.startswith(target_date) and self._is_valid_route_id(route_id)
        }
        sequence = 1
        while sequence in used_sequences:
            sequence += 1
        return self._format_route_id(target_date, sequence)

    @staticmethod
    def _write_json_file(path: str, payload: dict) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    @staticmethod
    def _is_valid_fs_name(name: str) -> bool:
        if not name or name in {".", ".."}:
            return False
        if any(char in name for char in _INVALID_FILE_NAME_CHARS):
            return False
        if name.endswith((" ", ".")):
            return False
        return True

    def _is_valid_route_name(self, name: str) -> bool:
        if not self._is_valid_fs_name(name):
            return False
        return f"{name}.json" not in {_PROGRESS_FILE, _RECENT_FILE, _VISIBILITY_FILE}

    @staticmethod
    def _is_valid_route_id(value: object) -> bool:
        return isinstance(value, str) and len(value) >= 10 and value.isdigit()
