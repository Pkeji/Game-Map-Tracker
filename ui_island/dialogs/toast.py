"""Non-blocking toast widgets."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..design import qss


class Toast(QWidget):
    _DISPLAY_MS = 1400
    _FADE_MS = 260

    def __init__(self, parent: QWidget, message: str, *, persistent: bool = False) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        qss.ensure_tooltip_style()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.setFocusPolicy(Qt.NoFocus)
        self._persistent = bool(persistent)

        shell = QFrame(self)
        shell.setObjectName("IslandRoot")
        row = QHBoxLayout(shell)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(10)

        icon = QLabel("✓")
        icon.setObjectName("ToastIcon")
        row.addWidget(icon)

        body = QLabel(message)
        body.setObjectName("BodyLabel")
        row.addWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(self._FADE_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(self._FADE_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.close)

    def pop(self, anchor: QWidget) -> None:
        self.adjustSize()
        anchor_geo = anchor.frameGeometry()
        x = anchor_geo.center().x() - self.width() // 2
        y = anchor_geo.top() + 60
        self.move(x, y)
        self.show()
        self._fade_in.start()
        if not self._persistent:
            QTimer.singleShot(self._DISPLAY_MS, self.dismiss)

    def dismiss(self) -> None:
        if self._fade_out.state() == QPropertyAnimation.Running:
            return
        self._fade_out.start()


def toast(parent: QWidget, message: str) -> None:
    instance = Toast(parent, message)
    instance.pop(parent)


def toast_persistent(parent: QWidget, message: str) -> Toast:
    instance = Toast(parent, message, persistent=True)
    instance.pop(parent)
    return instance
