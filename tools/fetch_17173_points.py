"""Fetch 17173 map points and export route JSON for this tracker.

This tool uses the fitted formula from the reference scraper.py:
  x = 5824.0800 * longitude + 7217.5810
  y = -5822.8413 * latitude + 6602.7721

Examples:
  python tools/fetch_17173_points.py 向阳花
  python tools/fetch_17173_points.py 17310030069
  python tools/fetch_17173_points.py fetch 魔力之源
  python tools/fetch_17173_points.py --list-categories
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Iterable

import requests

MAP_ID = 4010
API_URL = f"https://terra-api.17173.com/app/location/list?mapIds={MAP_ID}"
TOOL_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TOOL_DIR / "points_get"
CACHE_FILE = OUTPUT_DIR / ".cache_17173_locations.json"

# 来自参考 scraper.py 的手工标定拟合公式: 17173 API 坐标 -> 本项目导航地图像素坐标。
DEFAULT_SCALE_X = 5824.0800
DEFAULT_OFFSET_X = 7217.5810
DEFAULT_SCALE_Y = -5822.8413
DEFAULT_OFFSET_Y = 6602.7721

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://map.17173.com/rocom/maps/shijie",
    "Accept": "application/json, text/plain, */*",
}

CATEGORY_MAP: dict[str, str] = {
    "17310030001": "宝箱",
    "17310030002": "植物（果树）",
    "17310030003": "矿石",
    "17310030004": "未分类材料",
    "17310030005": "草系",
    "17310030006": "萌系",
    "17310030007": "火系",
    "17310030008": "虫系",
    "17310030009": "水系",
    "17310030010": "翼系",
    "17310030011": "幽系",
    "17310030012": "电系",
    "17310030013": "光系",
    "17310030014": "地系",
    "17310030015": "龙系",
    "17310030016": "毒系",
    "17310030017": "武系",
    "17310030018": "恶系",
    "17310030019": "幻系",
    "17310030020": "冰系",
    "17310030021": "普通系",
    "17310030022": "机械系",
    "17310030023": "未分类精灵",
    "17310030024": "BOSS（精灵首领）",
    "17310030025": "副本",
    "17310030026": "露天对战",
    "17310030027": "支线任务",
    "17310030028": "未分类任务",
    "17310030029": "挑战小游戏",
    "17310030030": "未分类内容",
    "17310030031": "精灵的宝藏",
    "17310030032": "精灵好感度植物",
    "17310030033": "魔法石",
    "17310030034": "魔法",
    "17310030035": "眠枭之星（蓝）",
    "17310030036": "崭新乐章",
    "17310030037": "稀有精灵",
    "17310030038": "魔力之源（传送点）",
    "17310030039": "眠枭庇护所",
    "17310030040": "稀兽花种",
    "17310030041": "炼金台",
    "17310030042": "未分类地点",
    "17310030043": "黄石榴石",
    "17310030044": "黑晶琉璃",
    "17310030045": "紫莲刚玉",
    "17310030046": "蓝晶碧玺",
    "17310030047": "眠枭之星（黄）",
    "17310030048": "幽幽鬼火",
    "17310030049": "恶魔雪茄",
    "17310030050": "彩玉花",
    "17310030051": "大嘴花",
    "17310030052": "短木莲",
    "17310030053": "藻羽花",
    "17310030054": "风卷草",
    "17310030055": "凤眼莲",
    "17310030056": "海桑花",
    "17310030057": "海神花",
    "17310030058": "花星角",
    "17310030059": "火焰花",
    "17310030060": "流星兰",
    "17310030061": "幽幽草",
    "17310030062": "密黄菌",
    "17310030063": "喵喵草",
    "17310030064": "喷气菇",
    "17310030065": "伞伞菇",
    "17310030066": "紫晶菇",
    "17310030067": "紫雀花",
    "17310030068": "天使草",
    "17310030069": "向阳花",
    "17310030070": "象牙花",
    "17310030071": "星霜花",
    "17310030072": "杏黄贝",
    "17310030073": "荧光兰",
    "17310030074": "雪菇",
    "17310030075": "蓝掌",
    "17310030076": "蜂窝",
    "17310030077": "骨片",
    "17310030078": "石耳",
    "17310030079": "睡铃",
    "17310030080": "可可果",
    "17310030081": "魔力果",
    "17310030082": "无花果",
}


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:")

    def format_help(self) -> str:
        text = super().format_help()
        replacements = {
            "usage:": "用法:",
            "positional arguments:": "位置参数:",
            "options:": "选项:",
            "optional arguments:": "选项:",
            "show this help message and exit": "显示帮助信息并退出",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: 错误: {message}\n")


def _safe_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    name = name.strip(" ._")
    return name or "17173_points"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_float(item: dict, *names: str) -> float:
    for name in names:
        if name in item:
            try:
                value = float(item[name])
            except (TypeError, ValueError):
                break
            if math.isfinite(value):
                return value
    raise ValueError(f"缺少有效数字字段: {'/'.join(names)}")


def latlng_to_xy(latitude: float, longitude: float) -> tuple[int, int]:
    x = DEFAULT_SCALE_X * longitude + DEFAULT_OFFSET_X
    y = DEFAULT_SCALE_Y * latitude + DEFAULT_OFFSET_Y
    return int(round(x)), int(round(y))


def fetch_all_locations(*, use_cache: bool = True, timeout: int = 30) -> list[dict]:
    if use_cache and CACHE_FILE.exists():
        data = _read_json(CACHE_FILE)
        if isinstance(data, list):
            return data

    response = requests.get(API_URL, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"17173 API 返回错误: {payload}")
    data = payload.get("data") or []
    if not isinstance(data, list):
        raise RuntimeError("17173 API 返回的数据不是列表")
    _write_json(CACHE_FILE, data)
    return data


def category_name(category_id: object) -> str:
    return CATEGORY_MAP.get(str(category_id), "")


def match_points(locations: list[dict], keyword: str, mode: str = "auto") -> list[dict]:
    keyword = keyword.strip()
    if not keyword:
        return []

    if mode in ("category", "auto"):
        exact_category_ids = [
            category_id
            for category_id, name in CATEGORY_MAP.items()
            if name == keyword
        ]
        if exact_category_ids:
            hits = [item for item in locations if str(item.get("category_id")) in exact_category_ids]
            if hits or mode == "category":
                return hits

        if re.fullmatch(r"\d+", keyword):
            hits = [item for item in locations if str(item.get("category_id")) == keyword]
            if hits or mode == "category":
                return hits

        partial_category_ids = [
            category_id
            for category_id, name in CATEGORY_MAP.items()
            if keyword in name
        ]
        if partial_category_ids:
            hits = [item for item in locations if str(item.get("category_id")) in partial_category_ids]
            if hits or mode == "category":
                return hits

    if mode in ("title", "auto"):
        return [item for item in locations if keyword in (item.get("title") or "")]
    return []


def suggest_similar(keyword: str, locations: list[dict], limit: int = 15) -> list[str]:
    titles = {item.get("title") for item in locations if item.get("title")}
    candidates = {name for name in CATEGORY_MAP.values() if name} | titles
    keyword = keyword.strip()
    scored = []
    for candidate in candidates:
        if keyword and keyword in candidate:
            scored.append((0, candidate))
            continue
        common = len(set(keyword) & set(candidate))
        if common >= max(1, len(keyword) // 2):
            scored.append((len(keyword) - common, candidate))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [candidate for _score, candidate in scored[:limit]]


def point_label(item: dict, index: int) -> str:
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    cat_name = category_name(item.get("category_id"))
    if cat_name:
        return cat_name
    return f"节点 {index}"


def points_to_route(points: list[dict], *, name: str, radius: int, loop: bool) -> dict:
    out_points = []
    for index, item in enumerate(points, 1):
        try:
            latitude = _as_float(item, "latitude")
            longitude = _as_float(item, "longitude")
        except ValueError:
            continue
        x, y = latlng_to_xy(latitude, longitude)
        out_points.append(
            {
                "x": x,
                "y": y,
                "label": point_label(item, index),
                "radius": radius,
            }
        )

    notes = (
        f"基于 17173 API mapIds={MAP_ID} 抓取. "
        "坐标使用参考 scraper.py 的拟合公式转换: "
        f"x={DEFAULT_SCALE_X:.4f}*longitude+{DEFAULT_OFFSET_X:.4f}, "
        f"y={DEFAULT_SCALE_Y:.4f}*latitude+{DEFAULT_OFFSET_Y:.4f}. "
        f"命中 {len(points)} 个点, 导出 {len(out_points)} 个有效节点."
    )
    return {
        "name": name,
        "loop": loop,
        "notes": notes,
        "points": out_points,
    }


def cmd_list_categories() -> int:
    for category_id, name in sorted(CATEGORY_MAP.items(), key=lambda item: item[0]):
        print(f"{category_id}  {name}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    locations = fetch_all_locations(use_cache=not args.refresh)
    print(f"[+] 已加载 {len(locations)} 个 17173 点位")

    hits = match_points(locations, args.keyword, mode=args.mode)
    if not hits:
        print(f"[!] 未找到匹配的 17173 点位: {args.keyword}")
        suggestions = suggest_similar(args.keyword, locations)
        if suggestions:
            print("[?] 你可能想找: " + ", ".join(suggestions))
        return 2

    out_path = Path(args.out) if args.out else OUTPUT_DIR / f"{_safe_name(args.keyword)}.json"
    route = points_to_route(hits, name=args.keyword, radius=args.radius, loop=args.loop)
    _write_json(out_path, route)
    print(f"[+] 命中 {len(hits)} 个点位，已导出 {len(route['points'])} 个路线节点")
    print(f"[+] 路线文件已保存: {out_path.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description="抓取 17173 点位并导出本项目可用的路线 JSON。")
    parser.add_argument(
        "keyword",
        nargs="?",
        help="分类名称、category_id 或标题关键字；也兼容旧写法前缀 fetch。",
    )
    parser.add_argument("legacy_keyword", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["auto", "title", "category"], default="auto", help="匹配模式: auto=分类优先后标题, title=只匹配标题, category=只匹配分类")
    parser.add_argument("--radius", type=int, default=30, help="导出路线节点的 radius 字段，默认 30")
    parser.add_argument("--loop", action="store_true", help="导出为闭环路线 loop=true")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存，重新从 17173 拉取数据")
    parser.add_argument("--out", help="输出路线 JSON 路径")
    parser.add_argument("--list-categories", action="store_true", help="列出已知分类 ID")
    return parser


def _resolve_keyword(args: argparse.Namespace) -> str:
    if args.keyword == "fetch" and args.legacy_keyword:
        return args.legacy_keyword
    return args.keyword or ""


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.list_categories or args.keyword == "list-categories":
            return cmd_list_categories()
        args.keyword = _resolve_keyword(args)
        if not args.keyword:
            parser.error("缺少关键字。示例: python tools/fetch_17173_points.py 向阳花")
        return cmd_fetch(args)
    except KeyboardInterrupt:
        print("\n[!] 已中断")
        return 130
    except Exception as exc:
        print(f"[!] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
