"""Fetch all 17173 collection points into a single annotation index.

Examples:
  python tools/fetch_17173_all_points.py
  python tools/fetch_17173_all_points.py --refresh
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from tools.fetch_17173_points import (
        MAP_ID,
        TOOL_DIR,
        _as_float,
        category_name,
        fetch_all_locations,
        icon_metadata_by_id,
        latlng_to_xy,
        point_label,
    )
except ModuleNotFoundError:
    from fetch_17173_points import (
        MAP_ID,
        TOOL_DIR,
        _as_float,
        category_name,
        fetch_all_locations,
        icon_metadata_by_id,
        latlng_to_xy,
        point_label,
    )

OUTPUT_DIR = TOOL_DIR / "points_all"
OUTPUT_FILE = OUTPUT_DIR / "points.json"
ICON_INDEX_FILE = TOOL_DIR / "points_icon" / "icons.json"


def build_all_points_index(locations: list[dict]) -> dict:
    icon_meta = icon_metadata_by_id()
    points_by_type: dict[str, list[dict]] = defaultdict(list)

    for index, item in enumerate(locations, 1):
        type_id = str(item.get("category_id") or "")
        if not type_id:
            continue
        try:
            latitude = _as_float(item, "latitude")
            longitude = _as_float(item, "longitude")
        except ValueError:
            continue
        x, y = latlng_to_xy(latitude, longitude)
        type_name = category_name(type_id)
        point = {
            "x": x,
            "y": y,
            "label": point_label(item, index),
            "type": type_name,
            "typeId": type_id,
        }
        source_id = item.get("id")
        if source_id is not None:
            point["sourceId"] = source_id
        points_by_type[type_id].append(point)

    types = []
    for type_id in sorted(points_by_type):
        meta = icon_meta.get(type_id, {})
        type_name = meta.get("type") or category_name(type_id) or type_id
        icon_path = f"{type_id}.png"
        types.append(
            {
                "typeId": type_id,
                "type": type_name,
                "groupId": meta.get("groupId") or "",
                "group": meta.get("group") or "其他",
                "iconPath": icon_path,
                "count": len(points_by_type[type_id]),
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mapId": MAP_ID,
        "types": types,
        "pointsByType": {type_id: points_by_type[type_id] for type_id in sorted(points_by_type)},
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取 17173 全部采集点位坐标并生成标注索引")
    parser.add_argument("--refresh", action="store_true", help="忽略点位缓存，重新请求 17173 接口")
    parser.add_argument("--out", default=str(OUTPUT_FILE), help="输出 JSON 文件路径")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not ICON_INDEX_FILE.exists():
        print(f"[!] 缺少图标索引: {ICON_INDEX_FILE}")
        print("[!] 请先运行: python tools/fetch_17173_icons.py")
        return 2
    try:
        locations = fetch_all_locations(use_cache=not args.refresh)
        payload = build_all_points_index(locations)
        write_json(Path(args.out), payload)
    except Exception as exc:
        print(f"[!] 抓取全部点位失败: {exc}", file=sys.stderr)
        return 1

    point_count = sum(len(points) for points in payload["pointsByType"].values())
    print(f"[+] 已导出 {point_count} 个点位，{len(payload['types'])} 个类别")
    print(f"[+] 点位索引已保存: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
