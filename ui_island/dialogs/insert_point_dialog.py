"""Dialog for inserting a map point into one or more tracked routes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..design import strings, tokens
from ..widgets.factory import make_label, make_scroll_area
from . import StyledDialogBase, center_dialog


class InsertPointDialog(StyledDialogBase):
    def __init__(self, parent, x: int, y: int, candidates: list[dict]) -> None:
        super().__init__(parent, strings.INSERT_POINT_DIALOG_TITLE, min_width=380, max_width=560)
        self._x = int(x)
        self._y = int(y)
        self._candidates = list(candidates)
        self._rows: list[dict] = []

        coord_lbl = make_label(strings.INSERT_POINT_COORD_FMT.format(x=self._x, y=self._y), object_name="BodyLabel")
        self.shell_layout.addWidget(coord_lbl)

        routes_lbl = make_label(strings.INSERT_POINT_ROUTES_LABEL, object_name="DimLabel")
        self.shell_layout.addWidget(routes_lbl)

        scroll = make_scroll_area(
            object_name="AnnotationPanelScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            min_height=120,
            max_height=260,
        )

        list_host = QWidget()
        list_host.setObjectName("AnnotationPanelInner")
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(2, 2, 2, 2)
        list_layout.setSpacing(6)

        single = len(self._candidates) == 1
        for cand in self._candidates:
            row_widget = QWidget()
            row_widget.setObjectName("InsertPointRouteRow")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            checkbox = QCheckBox(cand.get("display_label", ""))
            checkbox.setChecked(True)
            checkbox.setStyleSheet(f"color: {tokens.FG}; font-size: 12px;")
            row_layout.addWidget(checkbox, stretch=1)

            total = int(cand.get("points_count", 0))
            suggested = int(cand.get("suggested_index", 0))
            # UI 1-based: 第 N 位,N ∈ [1, total+1]
            suggested_ui = max(1, min(total + 1, suggested + 1))

            spin: QSpinBox | None = None
            if single:
                pos_lbl = make_label(strings.INSERT_POINT_POSITION_LABEL, object_name="DimLabel")
                row_layout.addWidget(pos_lbl)
                spin = QSpinBox()
                spin.setRange(1, total + 1)
                spin.setValue(suggested_ui)
                spin.setSuffix(f" / {total + 1}")
                row_layout.addWidget(spin)
            else:
                suggest_lbl = make_label(
                    strings.INSERT_POINT_SUGGEST_FMT.format(pos=suggested_ui, total=total + 1),
                    object_name="DimLabel",
                )
                row_layout.addWidget(suggest_lbl)

            list_layout.addWidget(row_widget)
            self._rows.append({
                "route_id": cand.get("route_id", ""),
                "suggested_index": suggested,
                "checkbox": checkbox,
                "spin": spin,
            })

        list_layout.addStretch(1)
        scroll.setWidget(list_host)
        self.shell_layout.addWidget(scroll, stretch=1)

        self._hint_label = QLabel("")
        self._hint_label.setObjectName("ErrorLabel")
        self._hint_label.setVisible(False)
        self.shell_layout.addWidget(self._hint_label)

        self.add_action_row(
            confirm_text=strings.INSERT_POINT_CONFIRM,
            cancel_text=strings.INSERT_POINT_CANCEL,
            on_confirm=self._on_confirm,
        )

        self.adjustSize()

    def selected_rows(self) -> list[dict]:
        return [row for row in self._rows if row["checkbox"].isChecked()]

    def selected_route_ids(self) -> list[str]:
        return [row["route_id"] for row in self.selected_rows() if row["route_id"]]

    def overrides(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in self.selected_rows():
            spin = row["spin"]
            rid = row["route_id"]
            if spin is None or not rid:
                continue
            ui_value = int(spin.value())
            if ui_value - 1 != int(row["suggested_index"]):
                result[rid] = ui_value - 1
        return result

    def _on_confirm(self) -> None:
        if not self.selected_rows():
            self._hint_label.setText(strings.INSERT_POINT_NO_SELECTION)
            self._hint_label.setVisible(True)
            return
        self.accept()


def open_insert_point_dialog(
    parent, x: int, y: int, candidates: list[dict]
) -> tuple[list[str], dict[str, int]] | None:
    dialog = InsertPointDialog(parent, x, y, candidates)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_route_ids(), dialog.overrides()
    return None
