"""Small styled text input dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .base import StyledDialogBase, center_dialog


class TextInputDialog(StyledDialogBase):
    def __init__(
        self,
        parent,
        *,
        title: str,
        label: str,
        value: str = "",
        placeholder: str = "",
        confirm_text: str = "确认",
        cancel_text: str = "取消",
    ) -> None:
        super().__init__(parent, title, min_width=360, max_width=460)

        text_label = QLabel(label)
        text_label.setObjectName("StatLabel")
        text_label.setWordWrap(True)
        self.shell_layout.addWidget(text_label)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(placeholder)
        self.input.setText(value)
        self.input.selectAll()
        self.shell_layout.addWidget(self.input)

        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = QPushButton(cancel_text)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(confirm_btn)

        self.shell_layout.addLayout(button_row)
        self.resize(380, 150)

    def value(self) -> str:
        return self.input.text().strip()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.input.setFocus(Qt.ActiveWindowFocusReason)


def prompt_text_input(
    parent,
    *,
    title: str,
    label: str,
    value: str = "",
    placeholder: str = "",
    confirm_text: str = "确认",
    cancel_text: str = "取消",
) -> tuple[bool, str]:
    dialog = TextInputDialog(
        parent,
        title=title,
        label=label,
        value=value,
        placeholder=placeholder,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
    )
    center_dialog(dialog, parent)
    accepted = dialog.exec() == QDialog.Accepted
    return accepted, dialog.value()
