"""灵动岛版跟点器主入口。

用法：
    python main_island.py            # 默认 SIFT 引擎
    python main_island.py --engine ai  # LoFTR AI 引擎（需 torch / kornia）
"""
from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

import config
from route_manager import RouteManager
from ui_island import IslandWindow
from ui_island.minimap_selector import run_minimap_calibrator


def build_tracker(engine: str):
    if engine == "ai":
        from engines import AiTracker  # 延迟导入，SIFT 用户不必装 torch
        return AiTracker()
    from engines import SiftTracker
    return SiftTracker()


def _minimap_is_configured() -> bool:
    cfg = config.settings.get("MINIMAP") or {}
    return bool(cfg) and "top" in cfg and "left" in cfg and "width" in cfg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["sift", "ai"], default="sift")
    parser.add_argument(
        "--no-selector",
        action="store_true",
        help="跳过小地图校准（使用 config.json 中已有坐标）",
    )
    parser.add_argument(
        "--force-selector",
        action="store_true",
        help="强制弹出小地图校准器即便已有坐标",
    )
    args = parser.parse_args()

    # Qt 应用必须先于选择器创建 —— 选择器本身就是 Qt 窗口
    app = QApplication(sys.argv)

    if args.force_selector or (not args.no_selector and not _minimap_is_configured()):
        print(">>> 正在启动小地图选择器...")
        saved = run_minimap_calibrator()
        if not saved:
            print("⚠️ 未保存小地图坐标，程序退出。")
            return 0
        print("<<< 选择器关闭，坐标已更新！")

    tracker = build_tracker(args.engine)
    route_mgr = RouteManager("routes")

    window = IslandWindow(tracker, route_mgr)
    window.show()
    return app.exec()


if __name__ == "__main__":
    # 用 os._exit 兜底：某些场景下 torch/kornia 等 C 扩展会留下非 daemon 线程，
    # 导致 sys.exit 阻塞终端不能立即返回提示符。
    code = main()
    os._exit(code if code is not None else 0)
