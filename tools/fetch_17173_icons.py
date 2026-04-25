"""Fetch 17173 point category icons for map route rendering.

Examples:
  python tools/fetch_17173_icons.py
  python tools/fetch_17173_icons.py --refresh
  python tools/fetch_17173_icons.py --apply-routes routes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests

try:
    import config
except Exception:
    config = None

MAP_PAGE_URL = "https://map.17173.com/rocom/maps/shijie"
TOOL_DIR = Path(config.app_path("tools")) if config is not None else Path(__file__).resolve().parent
ICON_DIR = TOOL_DIR / "points_icon"
ICON_INDEX_FILE = ICON_DIR / "icons.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": MAP_PAGE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _fetch_text(url: str, *, timeout: int = 30) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def _fetch_bytes(url: str, *, timeout: int = 30) -> bytes:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content


def _find_bootstrap_js(html: str) -> str:
    terra_matches = re.findall(r"https://ue\.17173cdn\.com/a/terra/web/bootstrap\.js\??", html)
    if terra_matches:
        return terra_matches[0]
    matches = re.findall(r"<script[^>]+src=[\"']([^\"']*bootstrap\.js[^\"']*)[\"']", html)
    if not matches:
        raise RuntimeError("未在 17173 地图页中找到 bootstrap.js")
    for match in matches:
        if "/a/terra/web/bootstrap.js" in match:
            return urljoin(MAP_PAGE_URL, match)
    return urljoin(MAP_PAGE_URL, matches[0])


def _find_app_js(bootstrap_js: str) -> list[str]:
    urls = re.findall(r"https://ue\.17173cdn\.com/a/terra/[^'\"\s]+\.js", bootstrap_js)
    urls.extend(re.findall(r"//ue\.17173cdn\.com/a/terra/[^'\"\s]+\.js", bootstrap_js))
    normalized = []
    seen = set()
    for url in urls:
        if url.startswith("//"):
            url = "https:" + url
        if url not in seen:
            seen.add(url)
            normalized.append(url)
    if not normalized:
        raise RuntimeError("未在 bootstrap.js 中找到前端资源 JS")
    return normalized


def _parse_icon_items(js_text: str) -> list[dict[str, str]]:
    group_names: dict[str, str] = {}
    group_pattern = re.compile(r"\{game_id:\d+,title:\"(?P<group_title>[^\"]+)\",id:(?P<group_id>\d+),categories:\[(?P<body>.*?)\]\}")
    item_pattern = re.compile(
        r"\{title:\"(?P<title>[^\"]+)\",group_id:(?P<group_id>\d+),id:(?P<id>\d+),icon:\"(?P<icon>https://ue\.17173cdn\.com/a/terra/icon/rocom/\d+\.png)\"\}"
    )
    for group_match in group_pattern.finditer(js_text):
        group_title = group_match.group("group_title")
        for item_match in item_pattern.finditer(group_match.group("body")):
            group_names[item_match.group("id")] = group_title

    pattern = item_pattern
    items = []
    seen = set()
    for match in pattern.finditer(js_text):
        type_id = match.group("id")
        if type_id in seen:
            continue
        seen.add(type_id)
        items.append(
            {
                "typeId": type_id,
                "type": match.group("title"),
                "groupId": match.group("group_id"),
                "group": group_names.get(type_id, "其他"),
                "iconUrl": match.group("icon"),
                "iconPath": f"{type_id}.png",
            }
        )
    items.sort(key=lambda item: item["typeId"])
    return items


def fetch_icon_metadata() -> list[dict[str, str]]:
    html = _fetch_text(MAP_PAGE_URL)
    bootstrap_url = _find_bootstrap_js(html)
    bootstrap_js = _fetch_text(bootstrap_url)
    app_urls = _find_app_js(bootstrap_js)

    for app_url in app_urls:
        js_text = _fetch_text(app_url)
        items = _parse_icon_items(js_text)
        if items:
            return items
    raise RuntimeError("未在 17173 前端资源中解析到图标分类定义")


def download_icons(items: list[dict[str, str]], *, refresh: bool) -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for item in items:
        path = ICON_DIR / item["iconPath"]
        if path.exists() and path.stat().st_size > 0 and not refresh:
            continue
        path.write_bytes(_fetch_bytes(item["iconUrl"]))
        downloaded += 1
    return downloaded


def _load_index() -> dict[str, dict[str, str]]:
    if not ICON_INDEX_FILE.exists():
        return {}
    with ICON_INDEX_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        return {}
    return {
        str(item.get("type")): item
        for item in payload
        if isinstance(item, dict) and item.get("type") and item.get("typeId")
    }


def _route_type_from_path(path: Path, route: dict, by_name: dict[str, dict[str, str]]) -> dict[str, str] | None:
    candidates = [
        str(route.get("name") or ""),
        str(route.get("display_name") or ""),
        path.stem,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in by_name:
            return by_name[candidate]
        for type_name, item in by_name.items():
            if type_name and type_name in candidate:
                return item
    return None


def apply_routes(routes_dir: Path) -> int:
    by_name = _load_index()
    if not by_name:
        raise RuntimeError(f"缺少图标索引，请先生成 {ICON_INDEX_FILE}")
    changed = 0
    for path in sorted(routes_dir.rglob("*.json")):
        if path.name in {"progress.json", "selected_routes.json", "recent_routes.json"}:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                route = json.load(handle)
        except Exception:
            continue
        if not isinstance(route, dict) or not isinstance(route.get("points"), list):
            continue
        item = _route_type_from_path(path, route, by_name)
        if item is None:
            continue
        route_changed = False
        for point in route["points"]:
            if not isinstance(point, dict) or point.get("typeId"):
                continue
            point["type"] = item["type"]
            point["typeId"] = item["typeId"]
            route_changed = True
        if route_changed:
            _write_json(path, route)
            changed += 1
    return changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取 17173 地图点位类别图标")
    parser.add_argument("--refresh", action="store_true", help="重新下载已存在的图标")
    parser.add_argument("--apply-routes", help="可选：回填指定 routes 目录中可识别路线的 type/typeId")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        items = fetch_icon_metadata()
        downloaded = download_icons(items, refresh=args.refresh)
        _write_json(ICON_INDEX_FILE, items)
        print(f"[+] 已解析 {len(items)} 个类别，下载 {downloaded} 个图标")
        print(f"[+] 图标索引已保存: {ICON_INDEX_FILE.resolve()}")
        if args.apply_routes:
            changed = apply_routes(Path(args.apply_routes))
            print(f"[+] 已回填 {changed} 个路线文件")
        return 0
    except Exception as exc:
        print(f"[!] 抓取 17173 图标失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
