"""路线管理：加载 / 绘制 / 进度持久化 / 动态着色。"""
from __future__ import annotations

import colorsys
import glob
import hashlib
import json
import math
import os
from typing import Iterable

import cv2


# 类别文件夹 -> 展示名
_DEFAULT_DISPLAY = {
    "zhiwu": "🌿 植物",
    "diquluxian": "📍 路线",
    "qita": "📦 其他",
}
_CLOSE_THRESHOLD = 20
_PROGRESS_FILE = "progress.json"
_VISIBILITY_FILE = "selected_routes.json"


def _color_for_name(name: str) -> tuple[int, int, int]:
    """哈希兜底：只在路线未被统一分配时使用。"""
    h = hashlib.md5(name.encode("utf-8")).digest()
    hue = h[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


class RouteManager:
    def __init__(self, base_folder: str = "routes") -> None:
        self.base_folder = base_folder
        self.categories: list[str] = []
        self.route_groups: dict[str, list[dict]] = {}
        self.visibility: dict[str, bool] = {}
        self._color_cache: dict[str, tuple[int, int, int]] = {}

        self._discover_categories()
        self._load_all_routes()
        self._assign_route_colors()
        self._load_visibility()
        self._load_progress()

    # ---------- 公开属性 ----------
    def category_display(self, cat: str) -> str:
        return _DEFAULT_DISPLAY.get(cat, cat)

    def color_for(self, name: str) -> tuple[int, int, int]:
        if name not in self._color_cache:
            self._color_cache[name] = _color_for_name(name)
        return self._color_cache[name]

    def iter_routes(self) -> Iterable[tuple[str, dict]]:
        for cat in self.categories:
            for r in self.route_groups[cat]:
                yield cat, r

    def visible_route_names(self) -> list[str]:
        return [
            route.get("display_name", "")
            for _cat, route in self.iter_routes()
            if self.visibility.get(route.get("display_name"), False)
        ]

    # ---------- 绘制 ----------
    def draw_on(self, canvas, vx1, vy1, view_size, player_x=None, player_y=None) -> None:
        local_player = None
        if player_x is not None and player_y is not None:
            local_player = (int(player_x - vx1), int(player_y - vy1))

        ch, cw = canvas.shape[:2]

        for _cat, route in self.iter_routes():
            name = route.get("display_name")
            if not self.visibility.get(name, False):
                continue

            pts = route.get("points", [])
            color = self.color_for(name)

            local_pts = [(int(p["x"] - vx1), int(p["y"] - vy1)) for p in pts]

            # 连线
            for i in range(len(local_pts) - 1):
                cv2.line(canvas, local_pts[i], local_pts[i + 1], color, 2, cv2.LINE_AA)
            if route.get("loop") and len(local_pts) > 2:
                cv2.line(canvas, local_pts[-1], local_pts[0], color, 2, cv2.LINE_AA)

            for i, (lp, p_dict) in enumerate(zip(local_pts, pts)):
                if not (0 <= lp[0] <= cw and 0 <= lp[1] <= ch):
                    continue

                visited = p_dict.get("visited", False)
                if not visited and local_player is not None:
                    dist = math.hypot(lp[0] - local_player[0], lp[1] - local_player[1])
                    if dist < _CLOSE_THRESHOLD:
                        p_dict["visited"] = True
                        visited = True

                # 节点圆：未踩用路线色，已踩变暗灰
                if visited:
                    dot_color = (45, 45, 45)
                    border_color = (90, 90, 90)
                    text_color = (100, 100, 100)
                else:
                    dot_color = color
                    border_color = (255, 255, 255)
                    text_color = color

                cv2.circle(canvas, lp, 5, dot_color, -1)
                cv2.circle(canvas, lp, 5, border_color, 1, cv2.LINE_AA)

                # 序号文字：黑色描边打底，路线色在上
                label = str(i + 1)
                tx, ty = lp[0] + 7, lp[1] - 4
                cv2.putText(canvas, label, (tx, ty),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(canvas, label, (tx, ty),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1, cv2.LINE_AA)

    def _assign_route_colors(self) -> None:
        """黄金比例 hue 递进：保证相邻路线色相间距最大。"""
        all_names = sorted(
            route.get("display_name", "")
            for _, route in self.iter_routes()
            if route.get("display_name")
        )
        for i, name in enumerate(all_names):
            hue = (i * 0.618033988749895) % 1.0   # 黄金角递进
            sat = 0.82 + (i % 4) * 0.045          # 0.82 / 0.865 / 0.91 / 0.955 交替
            val = 0.92 + (i % 2) * 0.07           # 0.92 / 0.99 交替
            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            self._color_cache[name] = (int(b * 255), int(g * 255), int(r * 255))

    # ---------- 加载 ----------
    def _discover_categories(self) -> None:
        if not os.path.isdir(self.base_folder):
            os.makedirs(self.base_folder, exist_ok=True)

        found = []
        for entry in sorted(os.listdir(self.base_folder)):
            full = os.path.join(self.base_folder, entry)
            if os.path.isdir(full):
                found.append(entry)

        # 保证默认类别存在，即便文件夹是空的
        for known in ("zhiwu", "diquluxian", "qita"):
            if known not in found:
                os.makedirs(os.path.join(self.base_folder, known), exist_ok=True)
                found.append(known)

        self.categories = found
        self.route_groups = {cat: [] for cat in self.categories}

    def _load_all_routes(self) -> None:
        for cat in self.categories:
            cat_path = os.path.join(self.base_folder, cat)
            for path in glob.glob(os.path.join(cat_path, "*.json")):
                try:
                    file_name = os.path.basename(path)
                    if file_name == _PROGRESS_FILE:
                        continue
                    route_name = os.path.splitext(file_name)[0]
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["display_name"] = route_name
                    # 每次启动都重置 visited，再由 progress.json 覆盖
                    for p in data.get("points", []):
                        p["visited"] = False
                    self.route_groups[cat].append(data)
                    self.visibility[route_name] = False
                except Exception as e:
                    print(f"加载失败 {path}: {e}")

    # ---------- 进度持久化 ----------
    def _progress_path(self) -> str:
        return os.path.join(self.base_folder, _PROGRESS_FILE)

    def _visibility_path(self) -> str:
        return os.path.join(self.base_folder, _VISIBILITY_FILE)

    def _load_visibility(self) -> None:
        path = self._visibility_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取路线勾选状态失败：{e}")
            return

        if not isinstance(data, list):
            return

        known_routes = set(self.visibility.keys())
        for name in data:
            if isinstance(name, str) and name in known_routes:
                self.visibility[name] = True

    def _load_progress(self) -> None:
        path = self._progress_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取路线进度失败：{e}")
            return

        for _cat, route in self.iter_routes():
            name = route.get("display_name")
            visited_idx = data.get(name, [])
            if not visited_idx:
                continue
            for i in visited_idx:
                if 0 <= i < len(route.get("points", [])):
                    route["points"][i]["visited"] = True

    def save_progress(self) -> None:
        data: dict[str, list[int]] = {}
        for _cat, route in self.iter_routes():
            name = route.get("display_name")
            visited = [
                i for i, p in enumerate(route.get("points", []))
                if p.get("visited", False)
            ]
            if visited:
                data[name] = visited
        try:
            with open(self._progress_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存路线进度失败：{e}")

    def reset_progress(self, name: str | None = None) -> None:
        """清空进度。name 为 None 时清全部。"""
        for _cat, route in self.iter_routes():
            if name is not None and route.get("display_name") != name:
                continue
            for p in route.get("points", []):
                p["visited"] = False
        self.save_progress()

    def save_visibility(self) -> None:
        try:
            with open(self._visibility_path(), "w", encoding="utf-8") as f:
                json.dump(self.visible_route_names(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存路线勾选状态失败：{e}")
