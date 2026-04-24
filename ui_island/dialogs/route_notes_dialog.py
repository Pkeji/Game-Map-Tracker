"""Dialog for viewing and editing route notes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from .base import StyledDialogBase, center_dialog
from ..design import strings, tokens


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
        self.editor.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: rgba(255, 255, 255, 0.08);
                color: {tokens.FG};
                border: 1px solid {tokens.BORDER};
                border-radius: 10px;
                padding: 8px 10px;
                font-size: 11px;
                selection-background-color: {tokens.ACCENT};
            }}
            QPlainTextEdit:focus {{
                border: 1px solid rgba(10, 132, 255, 0.65);
                background: rgba(10, 132, 255, 0.16);
            }}
            """
        )
        self.shell_layout.addWidget(self.editor, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = QPushButton(strings.ROUTE_NOTES_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        confirm_btn = QPushButton(strings.ROUTE_NOTES_CONFIRM)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(confirm_btn)

        self.shell_layout.addLayout(button_row)
        self.resize(460, 300)

    def notes_text(self) -> str:
        return self.editor.toPlainText()


def edit_route_notes(parent, route_name: str, notes: str) -> tuple[bool, str]:
    dialog = RouteNotesDialog(parent, route_name, notes)
    center_dialog(dialog, parent)
    accepted = dialog.exec() == QDialog.Accepted
    return accepted, dialog.notes_text()
