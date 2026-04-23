"""Reusable widgets for route list and status display."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from base import TrackState

from ..design import strings, tokens


class StatusDot(QWidget):
    COLORS = {
        TrackState.LOCKED: tokens.DOT_LOCKED,
        TrackState.INERTIAL: tokens.DOT_INERTIAL,
        TrackState.LOST: tokens.DOT_LOST,
        TrackState.SEARCHING: tokens.DOT_SEARCHING,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = tokens.DOT_SEARCHING
        self.setFixedSize(10, 10)

    def set_state(self, state: TrackState) -> None:
        new_color = self.COLORS.get(state, tokens.DOT_SEARCHING)
        if new_color != self._color:
            self._color = new_color
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self._color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())


class RouteSection(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._force_open = False
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setProperty("compact", True)
        self.header.setText(title)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.toggled.connect(self.set_expanded)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("RouteSectionBody")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 0, 4)
        self.body_layout.setSpacing(4)
        self.body_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)
        layout.addWidget(self.body)
        self._sync_state()

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._sync_state()

    def set_force_open(self, force_open: bool) -> None:
        self._force_open = force_open
        self._sync_state()

    def _sync_state(self) -> None:
        visible = self._expanded or self._force_open
        self.body.setVisible(visible)
        self.header.blockSignals(True)
        self.header.setChecked(self._expanded)
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)


class ElidedCheckBox(QCheckBox):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setToolTip(text)
        self._refresh_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elided_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elided_text()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _refresh_elided_text(self) -> None:
        metrics = QFontMetrics(self.font())
        available_width = max(60, self.width() - 24)
        super().setText(metrics.elidedText(self._full_text, Qt.ElideRight, available_width))


class RouteListItem(QWidget):
    def __init__(self, category: str, route_name: str, checked: bool, parent=None):
        super().__init__(parent)
        self.category = category
        self.route_name = route_name
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_row = QWidget(self)
        self.display_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.display_row.setMinimumWidth(0)
        display_layout = QHBoxLayout(self.display_row)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(6)

        self.checkbox = QCheckBox(route_name, self.display_row)
        self.checkbox.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
        self.checkbox.setChecked(checked)
        self.checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.checkbox.setMinimumWidth(0)
        self.checkbox.setToolTip(route_name)
        display_layout.addWidget(self.checkbox, stretch=1)

        self.rename_btn = QPushButton(strings.ROUTE_RENAME, self.display_row)
        self.rename_btn.setProperty("headerButton", True)
        self.rename_btn.setProperty("compact", True)
        display_layout.addWidget(self.rename_btn)

        self.delete_btn = QPushButton(strings.ROUTE_DELETE, self.display_row)
        self.delete_btn.setProperty("headerButton", True)
        self.delete_btn.setProperty("compact", True)
        display_layout.addWidget(self.delete_btn)

        self.edit_row = QWidget(self)
        self.edit_row.hide()
        self.edit_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.edit_row.setMinimumWidth(0)
        edit_layout = QHBoxLayout(self.edit_row)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(6)

        self.rename_input = QLineEdit(self.edit_row)
        self.rename_input.setPlaceholderText(strings.ROUTE_RENAME_PLACEHOLDER)
        self.rename_input.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.rename_input.setMinimumWidth(0)
        edit_layout.addWidget(self.rename_input, stretch=1)

        self.rename_confirm_btn = QPushButton("√", self.edit_row)
        self.rename_confirm_btn.setObjectName("HeaderWindowButton")
        self.rename_confirm_btn.setProperty("iconRole", "confirm")
        self.rename_confirm_btn.setToolTip(strings.ROUTE_RENAME_CONFIRM)
        self.rename_confirm_btn.setFixedWidth(26)
        edit_layout.addWidget(self.rename_confirm_btn)

        self.rename_cancel_btn = QPushButton("×", self.edit_row)
        self.rename_cancel_btn.setObjectName("HeaderWindowButton")
        self.rename_cancel_btn.setProperty("iconRole", "close")
        self.rename_cancel_btn.setToolTip(strings.ROUTE_RENAME_CANCEL)
        self.rename_cancel_btn.setFixedWidth(26)
        edit_layout.addWidget(self.rename_cancel_btn)

        layout.addWidget(self.display_row)
        layout.addWidget(self.edit_row)

    def start_rename(self) -> None:
        self.display_row.hide()
        self.edit_row.show()
        self.rename_input.setText(self.route_name)
        self.rename_input.selectAll()
        self.rename_input.setFocus()

    def cancel_rename(self) -> None:
        self.edit_row.hide()
        self.display_row.show()
        self.rename_input.clear()
        self.rename_input.setPlaceholderText(strings.ROUTE_RENAME_PLACEHOLDER)

    def is_renaming(self) -> bool:
        return self.edit_row.isVisible()

    def current_rename_value(self) -> str:
        return self.rename_input.text().strip()

    def show_rename_error(self, message: str) -> None:
        self.rename_input.clear()
        self.rename_input.setPlaceholderText(message)
        self.rename_input.setFocus()

    def update_route_name(self, route_name: str) -> None:
        self.route_name = route_name
        self.rename_input.setText(route_name)
        self._refresh_display_name()
        self.setToolTip(self.route_name)
        self.display_row.setToolTip(self.route_name)
        self.checkbox.setToolTip(self.route_name)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_display_name()

    def _refresh_display_name(self) -> None:
        metrics = QFontMetrics(self.checkbox.font())
        available_width = max(60, self.checkbox.width() - 28)
        display_name = metrics.elidedText(self.route_name, Qt.ElideRight, available_width)
        self.checkbox.setText(display_name)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class TrackedRouteItem(QWidget):
    def __init__(self, route_name: str, checked: bool, has_progress: bool, parent=None):
        super().__init__(parent)
        self.route_name = route_name
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.checkbox = ElidedCheckBox(route_name, self)
        self.checkbox.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
        self.checkbox.setChecked(checked)
        layout.addWidget(self.checkbox, stretch=1)

        self.reset_btn = QPushButton("重置进度", self)
        self.reset_btn.setProperty("headerButton", True)
        self.reset_btn.setProperty("compact", True)
        self.reset_btn.setToolTip("从第一个节点重新开始当前路线")
        self.reset_btn.setVisible(has_progress)
        layout.addWidget(self.reset_btn, alignment=Qt.AlignVCenter)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint
