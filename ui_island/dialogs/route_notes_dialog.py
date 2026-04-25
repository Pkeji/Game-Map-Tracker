"""Dialog for viewing and editing route notes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit

from .base import StyledDialogBase, center_dialog
from ..design import strings


class RouteNotesDialog(StyledDialogBase):
    def __init__(self, parent, route_name: str, notes: str) -> None:
        super().__init__(parent, strings.ROUTE_NOTES_TITLE, min_width=420, max_width=520)
        self._route_name = route_name

        subtitle = QLabel(f"路线：{route_name}")
        subtitle.setObjectName("StatLabel")
        subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(subtitle)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText(strings.ROUTE_NOTES_PLACEHOLDER)
        self.editor.setPlainText(notes)
        self.editor.setMinimumHeight(180)
        self.shell_layout.addWidget(self.editor, stretch=1)

        self.add_action_row(confirm_text=strings.ROUTE_NOTES_CONFIRM, cancel_text=strings.ROUTE_NOTES_CANCEL)
        self.resize(460, 300)

    def notes_text(self) -> str:
        return self.editor.toPlainText()


def edit_route_notes(parent, route_name: str, notes: str) -> tuple[bool, str]:
    dialog = RouteNotesDialog(parent, route_name, notes)
    center_dialog(dialog, parent)
    accepted = dialog.exec() == QDialog.Accepted
    return accepted, dialog.notes_text()
