"""Dialog for choosing an annotation type for a route node."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..design import strings, tokens
from . import StyledDialogBase, center_dialog


class AnnotationTypePickerDialog(StyledDialogBase):
    _COLUMNS = 3

    def __init__(self, parent, items: list[dict], current_type_id: str = "") -> None:
        super().__init__(parent, strings.ANNOTATION_TYPE_PICKER_TITLE, min_width=560, max_width=560)
        self._items = list(items)
        self._current_type_id = str(current_type_id or "")
        self._selected: dict | None = None

        if not self._items:
            empty = QLabel(strings.ANNOTATION_TYPE_PICKER_EMPTY)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {tokens.FG_DIM}; font-size: 12px;")
            self.shell_layout.addWidget(empty)
            self._add_cancel_row()
            self.adjustSize()
            return

        scroll = QScrollArea()
        scroll.setObjectName("AnnotationPanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(180)
        scroll.setMaximumHeight(360)

        host = QWidget()
        host.setObjectName("AnnotationPanelInner")
        groups_layout = QVBoxLayout(host)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(8)

        for group_name, group_items in self._grouped_items():
            title = QLabel(group_name)
            title.setObjectName("AnnotationGroupTitle")
            groups_layout.addWidget(title)

            grid_holder = QWidget()
            grid = QGridLayout(grid_holder)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            for index, item in enumerate(group_items):
                button = self._build_type_button(item)
                grid.addWidget(button, index // self._COLUMNS, index % self._COLUMNS)
            for column in range(self._COLUMNS):
                grid.setColumnStretch(column, 1)
            groups_layout.addWidget(grid_holder)

        groups_layout.addStretch(1)

        scroll.setWidget(host)
        self.shell_layout.addWidget(scroll, stretch=1)
        self._add_cancel_row()
        self.adjustSize()

    def _grouped_items(self) -> list[tuple[str, list[dict]]]:
        groups: dict[str, list[dict]] = {}
        group_order: list[str] = []
        for item in self._items:
            group_name = str(item.get("group") or "其他")
            if group_name not in groups:
                groups[group_name] = []
                group_order.append(group_name)
            groups[group_name].append(item)
        return [(group_name, groups[group_name]) for group_name in group_order]

    def _build_type_button(self, item: dict) -> QPushButton:
        type_id = str(item.get("typeId") or "")
        type_name = str(item.get("type") or type_id)
        count = item.get("count") or 0

        button = QPushButton(f"{type_name}  ·  {count}")
        button.setObjectName("AnnotationTypeRow")
        button.setProperty("selected", bool(type_id and type_id == self._current_type_id))
        button.setCheckable(True)
        button.setChecked(bool(type_id and type_id == self._current_type_id))
        button.setToolTip(type_name)
        button.setMinimumHeight(30)
        button.setIconSize(QSize(20, 20))

        icon_path = Path("tools") / "points_icon" / str(item.get("iconPath") or f"{type_id}.png")
        if icon_path.exists():
            button.setIcon(QIcon(QPixmap(str(icon_path))))

        button.clicked.connect(lambda _checked=False, known_item=dict(item): self._select(known_item))
        return button

    def _add_cancel_row(self) -> None:
        cancel_btn = QPushButton(strings.ANNOTATION_TYPE_PICKER_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(cancel_btn, alignment=Qt.AlignRight)
        self.shell_layout.addLayout(row)

    def _select(self, item: dict) -> None:
        self._selected = item
        self.accept()

    def selected_item(self) -> dict | None:
        return dict(self._selected) if self._selected is not None else None


def open_annotation_type_picker(parent, items: list[dict], current_type_id: str = "") -> dict | None:
    dialog = AnnotationTypePickerDialog(parent, items, current_type_id)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_item()
    return None
