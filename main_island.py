"""灵动岛版跟点器主入口。

用法：
    python main_island.py            # 默认 SIFT 引擎
    python main_island.py --engine ai  # LoFTR AI 引擎（需 torch / kornia）
"""
from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from bootstrap import run_selector_if_needed
from route_manager import RouteManager
from ui_island import IslandWindow


def build_tracker(engine: str):
    if engine == "ai":
        from engines import AiTracker  # 延迟导入，SIFT 用户不必装 torch
        return AiTracker()
    from engines import SiftTracker
    return SiftTracker()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["sift", "ai"], default="sift")
    parser.add_argument(
        "--no-selector",
        action="store_true",
        help="跳过小地图校准（使用 config.json 中已有坐标）",
    )
    args = parser.parse_args()

    if not args.no_selector:
        run_selector_if_needed()

    app = QApplication(sys.argv)
    tracker = build_tracker(args.engine)
    route_mgr = RouteManager("routes")

    window = IslandWindow(tracker, route_mgr)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
