"""Small helpers for consistently styled context menus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu


@dataclass(frozen=True)
class ContextMenuItem:
    text: str = ""
    callback: Callable[[], None] | None = None
    separator: bool = False
    enabled: bool = True
    visible: bool = True

    @classmethod
    def separator_item(cls) -> "ContextMenuItem":
        return cls(separator=True)


def _context_menu_style(parent) -> str:
    if parent is None:
        return ""
    style = parent.styleSheet() if hasattr(parent, "styleSheet") else ""
    if style:
        return style
    window = parent.window() if hasattr(parent, "window") else None
    return window.styleSheet() if window is not None and hasattr(window, "styleSheet") else ""


def show_context_menu(
    parent,
    global_pos,
    items: Iterable[ContextMenuItem],
    *,
    object_name: str = "",
) -> None:
    menu = QMenu(parent)
    if object_name:
        menu.setObjectName(object_name)
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_NoSystemBackground, True)
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    menu.setAutoFillBackground(False)
    menu.setStyleSheet(_context_menu_style(parent))

    has_actions = False
    for item in items:
        if not item.visible:
            continue
        if item.separator:
            menu.addSeparator()
            continue
        action = menu.addAction(item.text)
        action.setEnabled(item.enabled)
        has_actions = True
        if item.callback is not None:
            action.triggered.connect(lambda _checked=False, callback=item.callback: callback())

    if has_actions:
        menu.exec(global_pos)
