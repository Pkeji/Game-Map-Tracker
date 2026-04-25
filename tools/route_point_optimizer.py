"""Reusable route point optimization helpers and CLI.

Examples:
  python tools/route_point_optimizer.py tools/points_get/向阳花.json
  python tools/route_point_optimizer.py tools/points_get/向阳花.json -o 向阳花_路线.json
  python tools/route_point_optimizer.py tools/points_get/向阳花.json --start 1500,4000 --loop
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable


def point_distance(a: dict, b: dict) -> float:
    dx = a["x"] - b["x"]
    dy = a["y"] - b["y"]
    return math.hypot(dx, dy)


def total_route_length(points: list[dict], loop: bool = False) -> float:
    if len(points) < 2:
        return 0.0
    total = sum(point_distance(points[index], points[index + 1]) for index in range(len(points) - 1))
    if loop:
        total += point_distance(points[-1], points[0])
    return total


def best_insertion_index(points: list[dict], new_xy: tuple[float, float]) -> int:
    """Return the index that minimizes route length increase for a new point."""
    if not points:
        return 0
    if len(points) == 1:
        return 1

    nx, ny = float(new_xy[0]), float(new_xy[1])
    best_index = 0
    best_cost = math.hypot(nx - points[0]["x"], ny - points[0]["y"])

    for index in range(1, len(points)):
        prev, curr = points[index - 1], points[index]
        orig = math.hypot(curr["x"] - prev["x"], curr["y"] - prev["y"])
        detour = (
            math.hypot(nx - prev["x"], ny - prev["y"])
            + math.hypot(curr["x"] - nx, curr["y"] - ny)
            - orig
        )
        if detour < best_cost:
            best_cost = detour
            best_index = index

    tail_cost = math.hypot(nx - points[-1]["x"], ny - points[-1]["y"])
    if tail_cost < best_cost:
        best_index = len(points)

    return best_index


def nearest_neighbor(points: list[dict], start_idx: int = 0) -> list[dict]:
    remaining = points.copy()
    start = remaining.pop(start_idx)
    route = [start]
    while remaining:
        cur = route[-1]
        next_index = min(range(len(remaining)), key=lambda index: point_distance(cur, remaining[index]))
        route.append(remaining.pop(next_index))
    return route


def nearest_neighbor_from_point(points: list[dict], start: tuple[float, float]) -> list[dict]:
    """Start from an arbitrary x,y coordinate and repeatedly visit nearest point."""
    remaining = points.copy()
    sx, sy = start
    route: list[dict] = []
    cur = {"x": sx, "y": sy}
    while remaining:
        next_index = min(range(len(remaining)), key=lambda index: point_distance(cur, remaining[index]))
        route.append(remaining.pop(next_index))
        cur = route[-1]
    return route


def two_opt(points: list[dict], loop: bool = False, max_passes: int = 50) -> list[dict]:
    """Improve route order with 2-opt; suitable for small/medium point sets."""
    count = len(points)
    if count < 4:
        return points
    best = points[:]
    improved = True
    passes = 0
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for i in range(1 if not loop else 0, count - 2):
            for j in range(i + 1, count - (0 if loop else 1)):
                a, b = best[i - 1], best[i]
                c = best[j]
                d = best[(j + 1) % count] if loop else best[j + 1]
                old = point_distance(a, b) + point_distance(c, d)
                new = point_distance(a, c) + point_distance(b, d)
                if new + 1e-9 < old:
                    best[i : j + 1] = best[i : j + 1][::-1]
                    improved = True
    return best


def optimize_route_points(
    points: list[dict],
    start: tuple[float, float] | None = None,
    loop: bool = False,
    passes: int = 50,
) -> list[dict]:
    if not points:
        return []

    if start is not None:
        route = nearest_neighbor_from_point(points, start)
    else:
        best_route = None
        best_len = math.inf
        for index in range(min(8, len(points))):
            candidate = nearest_neighbor(points, start_idx=index)
            candidate_len = total_route_length(candidate, loop=loop)
            if candidate_len < best_len:
                best_len = candidate_len
                best_route = candidate
        route = best_route or points[:]

    return two_opt(route, loop=loop, max_passes=passes)


def relabel_points(points: list[dict]) -> list[dict]:
    """Return shallow-copied points relabeled as 节点 N."""
    relabeled = []
    for index, point in enumerate(points, 1):
        item = dict(point)
        item["label"] = f"节点 {index}"
        relabeled.append(item)
    return relabeled


def optimize_route_json(
    data: dict,
    source_name: str,
    start: tuple[float, float] | None = None,
    loop: bool | None = None,
    passes: int = 50,
    keep_label: bool = False,
) -> tuple[dict, dict]:
    points = data.get("points") or []
    if not isinstance(points, list) or not points:
        raise ValueError("输入路线 JSON 中没有 points")

    target_loop = bool(data.get("loop")) if loop is None else bool(loop)
    before = total_route_length(points, loop=target_loop)
    route = optimize_route_points(points, start=start, loop=target_loop, passes=passes)
    after = total_route_length(route, loop=target_loop)
    if not keep_label:
        route = relabel_points(route)

    output = dict(data)
    output["points"] = route
    output["loop"] = target_loop
    output["name"] = output.get("name", source_name) + "_路线"
    note = output.get("notes") or ""
    reduction = (1 - after / before) * 100 if before > 0 else 0
    output["notes"] = (
        (note + " | " if note else "")
        + f"已优化: {len(route)} 点, 总距离 {before:.0f} → {after:.0f} "
        f"({reduction:.1f}% 减少)"
    )
    stats = {
        "points": len(route),
        "before": before,
        "after": after,
        "reduction_percent": reduction,
        "loop": target_loop,
    }
    return output, stats


def _parse_start(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        sx, sy = [float(item) for item in value.split(",")]
    except Exception as exc:
        raise ValueError("--start 格式错误, 应为 x,y (例: 1500,4000)") from exc
    return sx, sy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="路线优化 (NN + 2-opt)")
    parser.add_argument("input", help="路线 json 文件")
    parser.add_argument("-o", "--out", help="输出文件 (默认在原文件名加 _路线)")
    parser.add_argument("--start", help="起点坐标 x,y (像素). 不指定则自动枚举起点选最短")
    parser.add_argument("--loop", action="store_true", help="闭环路径")
    parser.add_argument("--passes", type=int, default=50, help="2-opt 最大轮数")
    parser.add_argument("--keep-label", action="store_true", help="保留原 label, 不重命名")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    src = Path(args.input)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        start_xy = _parse_start(args.start)
        loop = True if args.loop else None
        output, stats = optimize_route_json(
            data,
            src.stem,
            start=start_xy,
            loop=loop,
            passes=args.passes,
            keep_label=args.keep_label,
        )
    except ValueError as exc:
        print(f"[!] {exc}")
        return 2

    out_path = Path(args.out) if args.out else src.with_name(src.stem + "_路线.json")
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[+] 优化完成: {stats['points']} 点, {stats['before']:.0f} → {stats['after']:.0f} "
        f"({stats['reduction_percent']:.1f}% ↓)"
    )
    print(f"[+] 已保存 -> {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
