"""Popup selector for route node types."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QButtonGroup, QFrame, QRadioButton, QVBoxLayout

from route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL, NODE_TYPES

from ..design import strings, theme


def normalize_node_type(value: object) -> str:
    node_type = str(value or NODE_TYPE_COLLECT).strip().casefold()
    return node_type if node_type in NODE_TYPES else NODE_TYPE_COLLECT


def node_type_items() -> tuple[tuple[str, str], ...]:
    return (
        (NODE_TYPE_COLLECT, strings.ROUTE_DRAWING_NODE_COLLECT),
        (NODE_TYPE_TELEPORT, strings.ROUTE_DRAWING_NODE_TELEPORT),
        (NODE_TYPE_VIRTUAL, strings.ROUTE_DRAWING_NODE_VIRTUAL),
    )


def node_type_label(value: object) -> str:
    normalized = normalize_node_type(value)
    for node_type, label in node_type_items():
        if node_type == normalized:
            return label
    return strings.ROUTE_DRAWING_NODE_COLLECT


class NodeTypePopup(QFrame):
    def __init__(
        self,
        parent,
        current_node_type: object,
        on_selected: Callable[[str], None],
    ) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self._current_node_type = normalize_node_type(current_node_type)
        self._on_selected = on_selected
        self.setObjectName("NodeTypePopup")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            theme.ISLAND_QSS
            + """
QFrame#NodeTypePopup QRadioButton {
    color: #f5f5f7;
    padding: 5px 8px;
    min-width: 92px;
}
QFrame#NodeTypePopup QRadioButton:hover {
    background: rgba(255, 255, 255, 28);
    border-radius: 5px;
}
"""
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for node_type, label in node_type_items():
            button = QRadioButton(label)
            button.setChecked(node_type == self._current_node_type)
            button.clicked.connect(lambda _checked=False, value=node_type: self._select(value))
            self._group.addButton(button)
            layout.addWidget(button)

    def paintEvent(self, _event) -> None:
        # Qt does not reliably paint QSS backgrounds on translucent top-level popups.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(28, 28, 30, 244))
        painter.setPen(QPen(QColor(255, 255, 255, 48), 1))
        painter.drawRoundedRect(rect, 8, 8)

    def _select(self, node_type: str) -> None:
        if node_type != self._current_node_type:
            self._on_selected(node_type)
        self.close()


def show_node_type_popup(
    parent,
    global_pos,
    current_node_type: object,
    on_selected: Callable[[str], None],
) -> NodeTypePopup:
    popup = NodeTypePopup(parent, current_node_type, on_selected)
    popup.adjustSize()

    pos = QPoint(global_pos)
    screen = QApplication.screenAt(pos) or (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        margin = 4
        x = min(max(available.left() + margin, pos.x()), available.right() - popup.width() - margin + 1)
        y = min(max(available.top() + margin, pos.y()), available.bottom() - popup.height() - margin + 1)
        pos = QPoint(x, y)

    popup.move(pos)
    popup.show()
    popup.raise_()
    return popup
