"""基于 PySide6 的小地图选区校准器，替代原 selector.py 的 Tk 实现。

流程：
  1. 在屏幕上显示一个半透明、可拖动、可滚轮缩放的绿色方框（准星）。
  2. 用户按回车或双击，先隐藏方框截图，弹出预览对话框让用户确认。
  3. 用户点确定 → 保存 MINIMAP 到 config.json 并返回；取消 → 可重新截取。
"""
from __future__ import annotations

from typing import Callable, Optional

import mss
import numpy as np

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config

from . import theme


_DEFAULT_SIZE = 150
_MIN_SIZE = 80
_SCROLL_STEP = 10


class _SelectorOverlay(QWidget):
    """半透明圆形准星窗：可拖动、可滚轮缩放、按回车/双击触发截图。"""

    confirm_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, x: int, y: int, size: int) -> None:
        # 不用 Qt.Tool —— 它在 Windows 下不接受键盘/鼠标事件聚焦，
        # 会把点击事件转发回"被 hide 的 parent"，触发系统"叮"响。
        # Qt.Window 保证自己就是顶层且能正常接收输入。
        super().__init__(
            None,
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowOpacity(0.55)
        self.setCursor(Qt.SizeAllCursor)

        self._size = max(_MIN_SIZE, int(size))
        self.setGeometry(int(x), int(y), self._size, self._size)
        self._drag_offset: Optional[QPoint] = None

    # ----- 公共访问 -----
    def region(self) -> tuple[int, int, int]:
        """返回**物理像素**坐标的 (x, y, size)，供 mss 截图和 config 持久化使用。

        Qt 的 geometry 是 device-independent（逻辑像素），在 Windows 高 DPI 缩放下
        和 mss 的物理像素不一致，需要乘以 devicePixelRatio。
        """
        g = self.frameGeometry()
        ratio = self.devicePixelRatioF() or 1.0
        return (
            int(round(g.x() * ratio)),
            int(round(g.y() * ratio)),
            int(round(self._size * ratio)),
        )

    # ----- 绘制 -----
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QColor(0, 0, 0, 180)
        painter.fillRect(self.rect(), bg)

        pen = QPen(QColor("#00FF00"))
        pen.setWidth(3)
        painter.setPen(pen)
        w = self._size
        painter.drawEllipse(3, 3, w - 6, w - 6)

        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, w // 2, w, w // 2)
        painter.drawLine(w // 2, 0, w // 2, w)

        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        painter.drawText(
            QRect(0, 6, w, 18),
            Qt.AlignCenter,
            "左键拖动 | 滚轮缩放",
        )
        painter.setPen(QColor("#ffd60a"))
        painter.drawText(
            QRect(0, w - 24, w, 18),
            Qt.AlignCenter,
            "按 回车/双击 确认截取",
        )

    # ----- 交互 -----
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.confirm_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        step = _SCROLL_STEP if delta > 0 else -_SCROLL_STEP
        self._resize_by(step)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm_requested.emit()
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)

    def _resize_by(self, delta: int) -> None:
        new_size = max(_MIN_SIZE, self._size + delta)
        if new_size == self._size:
            return
        cx = self.x() + self._size // 2
        cy = self.y() + self._size // 2
        self._size = new_size
        self.setGeometry(cx - new_size // 2, cy - new_size // 2, new_size, new_size)
        self.update()


class _PreviewDialog(QDialog):
    """截图预览对话框：与灵动岛 QSS 风格一致。

    三种结束方式：
      - 确定：accept，调用方读取后保存 config。
      - 重新截取：emit retake_requested + reject，调用方重开 overlay。
      - 关闭 × / Esc：emit cancel_requested + reject，调用方终止流程。
    """

    retake_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent, pixmap: QPixmap, x: int, y: int, size: int) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(theme.ISLAND_QSS)
        self.setModal(True)

        self._drag_offset: Optional[QPoint] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("IslandRoot")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 12, 18, 14)
        shell_layout.setSpacing(10)
        root.addWidget(shell)

        # 标题栏
        title_bar = QWidget()
        self._title_bar = title_bar
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(8)
        title = QLabel("确认小地图截取区域")
        title.setObjectName("TitleLabel")
        title.setStyleSheet("font-size: 14px;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        tb.addWidget(title)
        tb.addStretch()
        close = QPushButton("×")
        close.setObjectName("WindowControl")
        close.clicked.connect(self._on_close)
        tb.addWidget(close)
        shell_layout.addWidget(title_bar)

        # 截图
        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setStyleSheet("background: black; border-radius: 8px;")
        preview.setPixmap(pixmap)
        shell_layout.addWidget(preview, alignment=Qt.AlignCenter)

        info = QLabel(f"X: {x}   |   Y: {y}   |   尺寸: {size} × {size}")
        info.setStyleSheet(f"color: {theme.FG}; font-size: 12px; font-weight: 600;")
        info.setAlignment(Qt.AlignCenter)
        shell_layout.addWidget(info)

        # 按钮条
        btns = QHBoxLayout()
        btns.addStretch()
        retake = QPushButton("重新截取")
        retake.clicked.connect(self._on_retake)
        btns.addWidget(retake)
        ok = QPushButton("确定")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        shell_layout.addLayout(btns)

    def _on_retake(self) -> None:
        self.retake_requested.emit()
        self.reject()

    def _on_close(self) -> None:
        """× 按钮：取消整个校准流程。"""
        self.cancel_requested.emit()
        self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._on_close()
            return
        super().keyPressEvent(event)

    def _is_on_title_bar(self, global_pos: QPoint) -> bool:
        local = self._title_bar.mapFromGlobal(global_pos)
        return self._title_bar.rect().contains(local)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._is_on_title_bar(
            event.globalPosition().toPoint()
        ):
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
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


class MinimapCalibrator:
    """对外接口：封装"弹出选择器 → 截图预览 → 保存 config"的完整流程。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._parent = parent
        self._overlay: Optional[_SelectorOverlay] = None
        self._saved = False

    # ----- 入口 -----
    def run(self) -> bool:
        """阻塞地运行校准流程。返回 True 表示用户保存了配置。"""
        app = QApplication.instance()
        # 在 overlay 生命周期内禁用"关最后一个窗口就退出"，避免主窗被 hide 时
        # overlay 关闭触发整程序退出
        prev_quit_flag = None
        if app is not None:
            prev_quit_flag = app.quitOnLastWindowClosed()
            app.setQuitOnLastWindowClosed(False)

        try:
            x, y, size = self._initial_region()
            self._overlay = _SelectorOverlay(x, y, size)
            self._overlay.confirm_requested.connect(self._request_preview)
            self._overlay.cancel_requested.connect(self._cancel)
            self._overlay.show()
            self._overlay.activateWindow()
            self._overlay.raise_()
            self._overlay.setFocus(Qt.ActiveWindowFocusReason)

            # 用裸 QEventLoop 子事件循环等待
            self._loop = QEventLoop()
            self._overlay.destroyed.connect(lambda _=None: self._loop.quit())
            self._loop.exec()
        finally:
            if app is not None and prev_quit_flag is not None:
                app.setQuitOnLastWindowClosed(prev_quit_flag)
        return self._saved

    # ----- 内部 -----
    @staticmethod
    def _initial_region() -> tuple[int, int, int]:
        """读取上次保存的位置；没有则居中到主屏。返回**逻辑像素**（Qt setGeometry 用）。"""
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        if ratio <= 0:
            ratio = 1.0

        minimap = getattr(config, "MINIMAP", None) or {}
        try:
            # config 里存的是物理像素，先转回逻辑像素再给 Qt 用
            x_phys = int(minimap.get("left"))
            y_phys = int(minimap.get("top"))
            size_phys = int(minimap.get("width"))
            if size_phys < _MIN_SIZE:
                raise ValueError
            x = int(round(x_phys / ratio))
            y = int(round(y_phys / ratio))
            size = max(_MIN_SIZE, int(round(size_phys / ratio)))
            return _clamp_to_screen(x, y, size)
        except (TypeError, ValueError):
            pass
        # 默认：主屏正中心（Qt 可用区已经是逻辑像素）
        avail = screen.availableGeometry() if screen is not None else None
        size = _DEFAULT_SIZE
        if avail is None:
            return (100, 100, size)
        return (
            avail.x() + (avail.width() - size) // 2,
            avail.y() + (avail.height() - size) // 2,
            size,
        )

    def _request_preview(self) -> None:
        """隐藏 overlay，延迟一小会再截图防止绿框被截进去。"""
        assert self._overlay is not None
        self._overlay.hide()
        QTimer.singleShot(120, self._show_preview)

    def _show_preview(self) -> None:
        assert self._overlay is not None
        x, y, size = self._overlay.region()
        pixmap = _grab_region(x, y, size)
        dlg = _PreviewDialog(self._parent, pixmap, x, y, size)

        cancelled = {"v": False}

        def _on_cancel():
            cancelled["v"] = True
        dlg.retake_requested.connect(self._resume_overlay)
        dlg.cancel_requested.connect(_on_cancel)

        accepted = dlg.exec() == QDialog.Accepted
        if accepted:
            self._save_config(x, y, size)
            self._saved = True
            self._cancel()
        elif cancelled["v"]:
            # 用户点 × 或 Esc：终止整个流程
            self._cancel()
        # 否则是"重新截取"，_resume_overlay 已让 overlay 重新显示

    def _resume_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.show()
            self._overlay.activateWindow()
            self._overlay.setFocus()

    def _cancel(self) -> None:
        """关闭 overlay 以终止 run()。"""
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    @staticmethod
    def _save_config(x: int, y: int, size: int) -> None:
        config.save_config({
            "MINIMAP": {
                "top": int(y),
                "left": int(x),
                "width": int(size),
                "height": int(size),
            }
        })


# ============================================================
# 工具函数
# ============================================================
def _grab_region(x: int, y: int, size: int) -> QPixmap:
    """用 mss 截取指定区域，转成 QPixmap。"""
    with mss.mss() as sct:
        monitor = {"top": y, "left": x, "width": size, "height": size}
        raw = sct.grab(monitor)
        img = np.asarray(raw)  # BGRA
        h, w = img.shape[:2]
        # QImage 使用 RGB888 — 先转 RGB
        rgb = img[:, :, [2, 1, 0]].copy()
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)


def _clamp_to_screen(x: int, y: int, size: int) -> tuple[int, int, int]:
    """把初始位置夹紧到当前屏幕内，避免旧坐标跑出可视区。"""
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry() if screen is not None else None
    if avail is None:
        return x, y, size
    size = max(_MIN_SIZE, min(size, avail.width(), avail.height()))
    max_x = max(avail.left(), avail.right() - size)
    max_y = max(avail.top(), avail.bottom() - size)
    return (
        min(max(avail.left(), x), max_x),
        min(max(avail.top(), y), max_y),
        size,
    )


def run_minimap_calibrator(parent: Optional[QWidget] = None) -> bool:
    """顶层封装：实例化 MinimapCalibrator 并阻塞运行。"""
    return MinimapCalibrator(parent).run()
