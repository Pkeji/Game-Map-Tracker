"""Dialog for choosing an annotation type for a route node."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..design import strings
from ..widgets.annotation_type_widgets import build_annotation_type_button, group_annotation_types
from ..widgets.factory import make_scroll_area
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
            empty.setObjectName("DimLabel")
            self.shell_layout.addWidget(empty)
            self._add_cancel_row()
            self.adjustSize()
            return

        scroll = make_scroll_area(
            object_name="AnnotationPanelScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            min_height=180,
            max_height=360,
        )

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
        return group_annotation_types(self._items)

    def _build_type_button(self, item: dict) -> QPushButton:
        type_id = str(item.get("typeId") or "")
        button = build_annotation_type_button(
            item,
            selected=bool(type_id and type_id == self._current_type_id),
            min_height=30,
        )
        button.clicked.connect(lambda _checked=False, known_item=dict(item): self._select(known_item))
        return button

    def _add_cancel_row(self) -> None:
        self.add_action_row(cancel_text=strings.ANNOTATION_TYPE_PICKER_CANCEL)

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
