"""Collapsed restore icon for the island window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from base import TrackState

from ..design import qss, strings
from .route_widgets import StatusDot


class RestoreIcon(QWidget):
    _HEIGHT = 44

    def __init__(self, island_owner, on_restore, on_close) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(qss.ISLAND_QSS)
        self._on_restore = on_restore
        self._on_close_app = on_close
        self._drag_offset = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("IslandRoot")
        outer.addWidget(shell)

        row = QHBoxLayout(shell)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(8)

        self.dot = StatusDot(shell)
        self.dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.dot, alignment=Qt.AlignVCenter)

        self.coord_label = QLabel("-- , --", shell)
        self.coord_label.setObjectName("CoordLabel")
        self.coord_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.coord_label, alignment=Qt.AlignVCenter)

        restore_btn = QPushButton("▣")
        restore_btn.setObjectName("WindowControl")
        restore_btn.setFixedSize(self._HEIGHT - 12, self._HEIGHT - 12)
        restore_btn.setToolTip(strings.MINI_ICON_RESTORE)
        restore_btn.setCursor(Qt.PointingHandCursor)
        restore_btn.clicked.connect(self._on_restore)
        row.addWidget(restore_btn, alignment=Qt.AlignVCenter)

        close_btn = QPushButton("×")
        close_btn.setObjectName("WindowControl")
        close_btn.setFixedSize(self._HEIGHT - 12, self._HEIGHT - 12)
        close_btn.setToolTip(strings.MINI_ICON_CLOSE)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._on_close_app)
        row.addWidget(close_btn, alignment=Qt.AlignVCenter)

        self.setCursor(Qt.SizeAllCursor)
        self.setFixedHeight(self._HEIGHT)
        self.adjustSize()

    def set_state(self, state: TrackState) -> None:
        self.dot.set_state(state)

    def set_coord(self, text: str) -> None:
        self.coord_label.setText(text)

    def place_at(self, top_left) -> None:
        self.move(top_left.x(), top_left.y())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)
