"""Field definitions for the settings dialog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type_: type
    value_range: str = ""
    desc: str = ""
    needs_restart: bool = False


SIFT_FIELDS: list[Field] = [
    Field("SIFT_REFRESH_RATE", "刷新间隔", int, "10~100 ms", "越小越跟手"),
    Field("SIFT_MATCH_RATIO", "匹配比率", float, "0.6~0.95", "越大越宽松"),
    Field("SIFT_MIN_MATCH_COUNT", "最少匹配点", int, "4~20", "低于此值判丢失"),
    Field("SIFT_RANSAC_THRESHOLD", "RANSAC 阈值", float, "2.0~15.0 px", "越小越严格"),
    Field("SIFT_CLAHE_LIMIT", "CLAHE 对比度", float, "1.0~6.0", "对比度增强上限", needs_restart=True),
    Field("SIFT_LOCAL_SEARCH_RADIUS", "局部搜索半径", int, "200~800 px", "局部匹配范围"),
]

AI_FIELDS: list[Field] = [
    Field("AI_REFRESH_RATE", "刷新间隔", int, "50~500 ms", "AI 帧间隔"),
    Field("AI_CONFIDENCE_THRESHOLD", "置信阈值", float, "0.3~0.95", "越大越严"),
    Field("AI_MIN_MATCH_COUNT", "最少匹配点", int, "4~20", "低于此值判丢失"),
    Field("AI_RANSAC_THRESHOLD", "RANSAC 阈值", float, "2.0~15.0 px", "越小越严"),
    Field("AI_TRACK_RADIUS", "跟踪半径", int, "100~1000 px", "跟踪限定区域"),
    Field("AI_SCAN_SIZE", "扫描尺寸", int, "400~2000 px", "单次扫描窗大小", needs_restart=True),
    Field("AI_SCAN_STEP", "扫描步长", int, "300~1600 px", "扫描间隔", needs_restart=True),
]

COMMON_FIELDS: list[Field] = [
    Field("MAX_LOST_FRAMES", "最大惯性帧数", int, "10~120", "丢失判定阈值"),
    Field("ROUTE_RECENT_LIMIT", "最近路线条数", int, "3~10", "面板保留数量"),
    Field("ROUTE_GUIDE_NODE_DISTANCE", "导航节点偏离距离", int, "20~300 px", "超过此距离显示回到未访问节点的黑色指针"),
    Field("ROUTE_GUIDE_SEGMENT_DISTANCE", "导航线段吸附距离", int, "10~150 px", "靠近路线线段时显示下一目标指引"),
    Field("ROUTE_GUIDE_POINTER_SPACING", "导航指针间隔", int, "12~80 px", "连续黑色指针之间的距离"),
    Field("ROUTE_GUIDE_POINTER_SIZE", "导航指针尺寸", int, "5~30 px", "单个黑色指针的长度"),
]

TOOL_BUTTONS: list[str] = ["检查更新", "使用说明", "抓取点位", "路线编辑"]

ALL_FIELDS: list[Field] = SIFT_FIELDS + AI_FIELDS + COMMON_FIELDS
FIELD_INDEX: dict[str, Field] = {field.key: field for field in ALL_FIELDS}
