"""Reusable frameless dialog shell for island UI."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..design import qss, tokens


class StyledDialogBase(QDialog):
    def __init__(self, parent, title: str, *, modal: bool = True, min_width: int = 340, max_width: int = 460) -> None:
        super().__init__(parent)
        qss.ensure_tooltip_style()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.setModal(modal)

        self._drag_offset: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("IslandRoot")
        self.shell.setMinimumWidth(min_width)
        self.shell.setMaximumWidth(max_width)
        self.shell_layout = QVBoxLayout(self.shell)
        self.shell_layout.setContentsMargins(18, 12, 18, 14)
        self.shell_layout.setSpacing(10)
        root.addWidget(self.shell)

        self.title_bar = QWidget()
        self._title_bar = self.title_bar
        title_row = QHBoxLayout(self.title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("TitleLabel")
        title_lbl.setStyleSheet("font-size: 14px;")
        title_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WindowControl")
        self.close_btn.clicked.connect(self.reject)
        title_row.addWidget(self.close_btn)
        self.shell_layout.addWidget(self.title_bar)

    def _is_on_title_bar(self, global_pos: QPoint) -> bool:
        local = self._title_bar.mapFromGlobal(global_pos)
        return self._title_bar.rect().contains(local)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._is_on_title_bar(event.globalPosition().toPoint()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)


class StyledMessage(StyledDialogBase):
    def __init__(self, parent, title: str, message: str) -> None:
        super().__init__(parent, title)
        body = QLabel(message)
        body.setStyleSheet(f"color: {tokens.FG}; font-size: 12px;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(body, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(ok_btn)
        self.shell_layout.addLayout(button_row)
        self.adjustSize()


class StyledConfirm(StyledDialogBase):
    def __init__(self, parent, title: str, message: str, confirm_text: str = "确定", cancel_text: str = "取消") -> None:
        super().__init__(parent, title)
        body = QLabel(message)
        body.setStyleSheet(f"color: {tokens.FG}; font-size: 12px;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(body, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        ok_btn = QPushButton(confirm_text)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(ok_btn)
        self.shell_layout.addLayout(button_row)
        self.adjustSize()


def center_dialog(dialog: QDialog, parent) -> None:
    if parent is None:
        return
    parent_geo = parent.frameGeometry()
    dialog.move(
        parent_geo.center().x() - dialog.width() // 2,
        parent_geo.center().y() - dialog.height() // 2,
    )


def place_left_of(dialog: QDialog, anchor: QWidget) -> None:
    anchor_geo = anchor.frameGeometry()
    screen = anchor.screen() if hasattr(anchor, "screen") else None
    avail = screen.availableGeometry() if screen is not None else None

    target_x = anchor_geo.left() - dialog.width()
    target_y = anchor_geo.top()
    if avail is not None:
        if target_x < avail.left():
            target_x = avail.left()
        target_y = max(avail.top(), min(target_y, avail.bottom() - dialog.height()))
    dialog.move(target_x, target_y)
