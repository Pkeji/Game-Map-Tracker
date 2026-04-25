"""Shared builders for annotation type rows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton


def group_annotation_types(items: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    group_order: list[str] = []
    for item in items:
        group_name = str(item.get("group") or "其他")
        if group_name not in groups:
            groups[group_name] = []
            group_order.append(group_name)
        groups[group_name].append(item)
    return [(group_name, groups[group_name]) for group_name in group_order]


def annotation_icon_path(item: dict, type_id: str) -> Path:
    return Path("tools") / "points_icon" / str(item.get("iconPath") or f"{type_id}.png")


def annotation_type_button_text(item: dict, type_id: str | None = None) -> str:
    known_type_id = str(type_id if type_id is not None else item.get("typeId") or "")
    type_name = str(item.get("type") or known_type_id)
    return f"{type_name}  ·  {item.get('count') or 0}"


def build_annotation_type_button(
    item: dict,
    *,
    selected: bool,
    parent=None,
    fade_icon: bool = False,
    strike_out: bool = False,
    min_height: int | None = None,
    icon_size: int | None = 20,
) -> QPushButton:
    type_id = str(item.get("typeId") or "")
    type_name = str(item.get("type") or type_id)

    button = QPushButton(annotation_type_button_text(item, type_id), parent)
    button.setObjectName("AnnotationTypeRow")
    button.setProperty("selected", bool(selected))
    button.setCheckable(True)
    button.setChecked(bool(selected))
    button.setToolTip(type_name)
    if icon_size is not None:
        button.setIconSize(QSize(icon_size, icon_size))
    if min_height is not None:
        button.setMinimumHeight(min_height)

    if strike_out:
        font = button.font()
        font.setStrikeOut(not selected)
        button.setFont(font)

    icon_path = annotation_icon_path(item, type_id)
    if icon_path.exists():
        pixmap = QPixmap(str(icon_path))
        if fade_icon and not selected:
            pixmap = _faded_pixmap(pixmap, 0.35)
        button.setIcon(QIcon(pixmap))
    return button


def _faded_pixmap(pixmap: QPixmap, opacity: float) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    faded = QPixmap(pixmap.size())
    faded.fill(Qt.transparent)
    painter = QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return faded
