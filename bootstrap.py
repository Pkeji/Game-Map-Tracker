"""通用启动工具：小地图校准器拉起 / 配置热重载。

原先三个 main_*.py 各自实现了一份几乎相同的 run_selector_if_needed，
这里统一抽出来。
"""
import importlib
import os
import subprocess
import sys

import config


def _selector_command():
    """根据运行模式（源码 / PyInstaller 打包）返回要启动的命令行。"""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
        selector_path = os.path.join(base_dir, "MinimapSetup.exe")
        return [selector_path], selector_path

    base_dir = os.path.dirname(os.path.abspath(__file__))
    selector_path = os.path.join(base_dir, "selector.py")
    return [sys.executable, selector_path], selector_path


def run_selector_if_needed(force: bool = False) -> None:
    """在缺少坐标或 force=True 时阻塞地拉起小地图选择器，并刷新 config。"""
    minimap_cfg = config.settings.get("MINIMAP", {})
    has_valid = minimap_cfg and "top" in minimap_cfg and "left" in minimap_cfg

    if has_valid and not force:
        return

    print(">>> 正在启动小地图选择器...")
    command, selector_path = _selector_command()

    try:
        subprocess.run(command, check=True)
        importlib.reload(config)
        print("<<< 选择器关闭，坐标已更新！")
    except FileNotFoundError:
        print(f"❌ 找不到小地图选择器：{selector_path}")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("⚠️ 选择器异常退出，可能未保存坐标。")
