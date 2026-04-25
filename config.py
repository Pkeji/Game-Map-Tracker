import json
import os
import sys

# ==========================================
# 核心黑科技：兼容 PyInstaller 打包后的路径寻找
# ==========================================
if getattr(sys, 'frozen', False):
    # 如果是打包后的 .exe 运行，去 exe 所在的同级目录找配置文件
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是在代码编辑器里直接运行 main.py，去当前代码所在的目录找
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# ==========================================
# 默认配置字典 (如果 JSON 文件丢失，用来兜底并重新生成)
# ==========================================
DEFAULT_CONFIG = {
    # 首次启动时保持为空，强制弹出小地图校准器；保存后再写入真实坐标
    "MINIMAP": {},
    "WINDOW_GEOMETRY": {"x": 1418, "y": 0, "width": 420, "height": 360},
    "LOCKED_VIEW_SIZE": {"width": 420, "height": 360},
    "PAUSED_VIEW_SIZE": {"width": 820, "height": 500},
    "SIDEBAR_COLLAPSED": True,
    "SIDEBAR_WIDTH": 270,
    "PAUSED_SIDEBAR_WIDTH": 270,
    "VIEW_SIZE": 400,
    "LOGIC_MAP_PATH": "big_map.png",
    "MAX_LOST_FRAMES": 30,

    "SIFT_REFRESH_RATE": 10,
    "SIFT_CLAHE_LIMIT": 3.0,
    "SIFT_MATCH_RATIO": 0.9,
    "SIFT_MIN_MATCH_COUNT": 5,
    "SIFT_RANSAC_THRESHOLD": 8.0,
    "SIFT_LOCAL_SEARCH_RADIUS": 400,

    "ROUTE_RECENT_LIMIT": 5,
    "ROUTE_GUIDE_NODE_DISTANCE": 80,
    "ROUTE_GUIDE_SEGMENT_DISTANCE": 35,
    "ROUTE_GUIDE_POINTER_SPACING": 28,
    "ROUTE_GUIDE_POINTER_SIZE": 10,
    "ROUTE_SECTION_EXPANDED": {},
    "ANNOTATION_TYPE_IDS": [],
    "ANNOTATION_RECENT_TYPE_IDS": [],
}


def save_config(new_values: dict) -> None:
    """把部分字段写回 config.json 并刷新本模块导出的常量。"""
    current = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    current.update(new_values)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=4, ensure_ascii=False)

    # 同步更新模块级常量，避免进程内各处读到旧值
    globals().update(new_values)
    settings.update(new_values)


def load_config():
    """读取 JSON 配置文件，如果没有则自动生成"""
    if not os.path.exists(CONFIG_FILE):
        print("未找到 config.json，正在自动生成默认配置文件...")
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"生成配置文件失败: {e}")
        return DEFAULT_CONFIG

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = json.load(f)

            # 巧妙的合并逻辑：防止用户在 JSON 里少填了某个字段导致程序崩溃
            merged_config = DEFAULT_CONFIG.copy()
            merged_config.update(user_config)
            return merged_config
    except Exception as e:
        print(f"⚠️ 读取 config.json 失败 (格式错误?)，将临时使用默认配置！错误: {e}")
        return DEFAULT_CONFIG


# ==========================================
# 加载配置并导出变量 (让 main.py 可以直接 import 这些变量)
# ==========================================
settings = load_config()

# 通用设置
MINIMAP = settings.get("MINIMAP")
WINDOW_GEOMETRY = settings.get("WINDOW_GEOMETRY")
SIDEBAR_COLLAPSED = settings.get("SIDEBAR_COLLAPSED")
SIDEBAR_WIDTH = settings.get("SIDEBAR_WIDTH")
PAUSED_SIDEBAR_WIDTH = settings.get("PAUSED_SIDEBAR_WIDTH")
LOCKED_VIEW_SIZE = settings.get("LOCKED_VIEW_SIZE")
PAUSED_VIEW_SIZE = settings.get("PAUSED_VIEW_SIZE")
ROUTE_SECTION_EXPANDED = settings.get("ROUTE_SECTION_EXPANDED") or {}
ANNOTATION_TYPE_IDS = settings.get("ANNOTATION_TYPE_IDS") or []
ANNOTATION_RECENT_TYPE_IDS = settings.get("ANNOTATION_RECENT_TYPE_IDS") or []


def parse_window_geometry(raw) -> dict | None:
    """把旧的 Tk 字符串或新字典格式规整成 {x, y, width, height}。

    支持：
      - 字典 {x, y, width, height}
      - Tk 格式 "WxH+X+Y"
    无效输入返回 None。
    """
    if isinstance(raw, dict):
        try:
            return {
                "x": int(raw["x"]),
                "y": int(raw["y"]),
                "width": int(raw["width"]),
                "height": int(raw["height"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, str):
        import re
        m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", raw.strip())
        if m:
            w, h, x, y = m.groups()
            try:
                return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
            except ValueError:
                return None
    return None
VIEW_SIZE = settings.get("VIEW_SIZE")
LOGIC_MAP_PATH = settings.get("LOGIC_MAP_PATH")
MAX_LOST_FRAMES = settings.get("MAX_LOST_FRAMES")

# SIFT 专属
SIFT_REFRESH_RATE = settings.get("SIFT_REFRESH_RATE")
SIFT_CLAHE_LIMIT = settings.get("SIFT_CLAHE_LIMIT")
SIFT_MATCH_RATIO = settings.get("SIFT_MATCH_RATIO")
SIFT_MIN_MATCH_COUNT = settings.get("SIFT_MIN_MATCH_COUNT")
SIFT_RANSAC_THRESHOLD = settings.get("SIFT_RANSAC_THRESHOLD")
SIFT_LOCAL_SEARCH_RADIUS = settings.get("SIFT_LOCAL_SEARCH_RADIUS")

ROUTE_RECENT_LIMIT = settings.get("ROUTE_RECENT_LIMIT")
ROUTE_GUIDE_NODE_DISTANCE = settings.get("ROUTE_GUIDE_NODE_DISTANCE")
ROUTE_GUIDE_SEGMENT_DISTANCE = settings.get("ROUTE_GUIDE_SEGMENT_DISTANCE")
ROUTE_GUIDE_POINTER_SPACING = settings.get("ROUTE_GUIDE_POINTER_SPACING")
ROUTE_GUIDE_POINTER_SIZE = settings.get("ROUTE_GUIDE_POINTER_SIZE")
