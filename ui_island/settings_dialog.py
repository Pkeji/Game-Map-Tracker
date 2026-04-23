"""设置对话框：让用户修改 config.json 里的常用参数。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QDoubleValidator, QIntValidator, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config

from . import theme


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type_: type  # int 或 float
    value_range: str = ""  # 推荐范围，如 "10~100 ms"
    desc: str = ""
    needs_restart: bool = False  # 是否需要重启才生效


# 字段按版块分组
_SIFT_FIELDS: list[Field] = [
    Field("SIFT_REFRESH_RATE", "刷新间隔", int,
          "10~100 ms", "越小越跟手"),
    Field("SIFT_MATCH_RATIO", "匹配比率", float,
          "0.6~0.95", "越大越宽松"),
    Field("SIFT_MIN_MATCH_COUNT", "最少匹配点", int,
          "4~20", "低于此值判丢失"),
    Field("SIFT_RANSAC_THRESHOLD", "RANSAC 阈值", float,
          "2.0~15.0 px", "越小越严格"),
    Field("SIFT_CLAHE_LIMIT", "CLAHE 对比度", float,
          "1.0~6.0", "对比度增强上限", needs_restart=True),
    Field("SIFT_LOCAL_SEARCH_RADIUS", "局部搜索半径", int,
          "200~800 px", "局部匹配范围"),
]

_AI_FIELDS: list[Field] = [
    Field("AI_REFRESH_RATE", "刷新间隔", int,
          "50~500 ms", "AI 帧间隔"),
    Field("AI_CONFIDENCE_THRESHOLD", "置信阈值", float,
          "0.3~0.95", "越大越严"),
    Field("AI_MIN_MATCH_COUNT", "最少匹配点", int, "4~20", "低于此值判丢失"),
    Field("AI_RANSAC_THRESHOLD", "RANSAC 阈值", float, "2.0~15.0 px", "越小越严"),
    Field("AI_TRACK_RADIUS", "跟踪半径", int, "100~1000 px", "跟踪限定区域"),
    Field("AI_SCAN_SIZE", "扫描尺寸", int, "400~2000 px", "单次扫描窗大小",
          needs_restart=True),
    Field("AI_SCAN_STEP", "扫描步长", int, "300~1600 px", "扫描间隔",
          needs_restart=True),
]

_COMMON_FIELDS: list[Field] = [
    Field("MAX_LOST_FRAMES", "最大惯性帧数", int,
          "10~120", "丢失判定阈值"),
    Field("ROUTE_RECENT_LIMIT", "最近路线条数", int,
          "3~10", "面板保留数量"),
]

# 右下角的工具按钮（功能暂未实现，仅占位 UI）
_TOOL_BUTTONS: list[str] = ["检查更新", "使用说明", "抓取点位", "路线编辑"]


_ALL_FIELDS: list[Field] = _SIFT_FIELDS + _AI_FIELDS + _COMMON_FIELDS
_FIELD_INDEX: dict[str, Field] = {f.key: f for f in _ALL_FIELDS}


# ============================================================
# 统一风格的模态提示框（替代 QMessageBox）
# ============================================================
class StyledMessage(QDialog):
    """与灵动岛 QSS 统一的简单提示框：标题 + 正文 + 一个确定按钮。"""

    def __init__(self, parent, title: str, message: str) -> None:
        super().__init__(parent)
        theme.ensure_tooltip_style()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(theme.ISLAND_QSS)
        self.setModal(True)

        self._drag_offset: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("IslandRoot")
        shell.setMinimumWidth(340)
        shell.setMaximumWidth(460)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 12, 18, 14)
        shell_layout.setSpacing(10)
        root.addWidget(shell)

        title_bar = QWidget()
        self._title_bar = title_bar
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("TitleLabel")
        title_lbl.setStyleSheet("font-size: 14px;")
        title_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        close_btn = QPushButton("×")
        close_btn.setObjectName("WindowControl")
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn)
        shell_layout.addWidget(title_bar)

        body = QLabel(message)
        body.setStyleSheet(f"color: {theme.FG}; font-size: 12px;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        shell_layout.addWidget(body, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        shell_layout.addLayout(btn_row)

        self.adjustSize()

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


class Toast(QWidget):
    """自消散气泡：顶部弹出、停留 1.4s、淡出消失，不阻塞任何操作。"""

    _DISPLAY_MS = 1400
    _FADE_MS = 260

    def __init__(self, parent: QWidget, message: str) -> None:
        # 用独立 Tool 窗口而不是子 widget，避免 parent 有限 clip 区域
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        theme.ensure_tooltip_style()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(theme.ISLAND_QSS)
        self.setFocusPolicy(Qt.NoFocus)

        shell = QFrame(self)
        shell.setObjectName("IslandRoot")
        row = QHBoxLayout(shell)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(10)

        icon = QLabel("✓")
        icon.setStyleSheet(
            f"color: {theme.DOT_LOCKED}; font-size: 16px; font-weight: 700;"
        )
        row.addWidget(icon)

        body = QLabel(message)
        body.setStyleSheet(f"color: {theme.FG}; font-size: 12px;")
        row.addWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(shell)

        # 透明度动画
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
        """在 anchor 顶部居中弹出。"""
        self.adjustSize()
        ag = anchor.frameGeometry()
        x = ag.center().x() - self.width() // 2
        y = ag.top() + 60
        self.move(x, y)
        self.show()
        self._fade_in.start()
        QTimer.singleShot(self._DISPLAY_MS, self._fade_out.start)


def toast(parent: QWidget, message: str) -> None:
    t = Toast(parent, message)
    t.pop(parent)


def styled_info(parent, title: str, message: str) -> None:
    dlg = StyledMessage(parent, title, message)
    # 居中到 parent
    if parent is not None:
        pg = parent.frameGeometry()
        dlg.move(
            pg.center().x() - dlg.width() // 2,
            pg.center().y() - dlg.height() // 2,
        )
    dlg.exec()


# ============================================================
# 设置主窗口
# ============================================================
class SettingsDialog(QDialog):
    """灵动岛风格的设置窗口，固定大小，非模态。"""

    applied = Signal()
    restart_requested = Signal()

    _FIXED_WIDTH = 660
    _FIXED_HEIGHT = 620
    _SHELL_H_MARGIN = 18
    _SHELL_TOP_MARGIN = 12
    _SHELL_BOTTOM_MARGIN = 14
    _SECTION_H_MARGIN = 14
    _SECTION_TOP_MARGIN = 12
    _SECTION_BOTTOM_MARGIN = 12

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        theme.ensure_tooltip_style()
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(theme.ISLAND_QSS)
        self.resize(self._FIXED_WIDTH, self._FIXED_HEIGHT)

        self._drag_offset: QPoint | None = None
        self._editors: dict[str, QLineEdit] = {}
        self._initial_values: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("IslandRoot")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 12, 18, 14)
        shell_layout.setSpacing(10)
        root.addWidget(shell)

        # ---- 标题栏：标题 + 说明 ----
        title_bar = QWidget()
        self._title_bar = title_bar
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        title = QLabel("设置")
        title.setObjectName("TitleLabel")
        title.setStyleSheet("font-size: 14px;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(title)

        subtitle = QLabel(
            "修改后点击“应用”写回 config.json；标记 ⟲ 的参数需重启才生效。"
        )
        subtitle.setObjectName("StatLabel")
        subtitle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_row.addWidget(subtitle, stretch=1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("WindowControl")
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn)

        shell_layout.addWidget(title_bar)

        minimap_row = self._build_minimap_row()
        common_section = self._build_section(
            "通用设置", _COMMON_FIELDS,
            two_columns=True, narrow_editor=True,
            extra_widget=minimap_row,
        )
        tools_section = self._build_tools_section()

        # ---- 底部按钮条 ----
        buttons_bar = QWidget()
        btn_row = QHBoxLayout(buttons_bar)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        btn_row.addStretch()

        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._on_reset_defaults)
        btn_row.addWidget(reset_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("应用")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        apply_restart_btn = QPushButton("应用并重启")
        apply_restart_btn.clicked.connect(self._on_apply_and_restart)
        btn_row.addWidget(apply_restart_btn)

        top_section_max_height = self._compute_top_section_max_height(
            title_bar_height=title_bar.sizeHint().height(),
            bottom_row_height=max(
                common_section.sizeHint().height(),
                tools_section.sizeHint().height(),
            ),
            button_row_height=buttons_bar.sizeHint().height(),
            shell_spacing=shell_layout.spacing(),
        )

        # ---- SIFT / AI 并列 ----
        columns = QHBoxLayout()
        columns.setSpacing(10)
        columns.addWidget(
            self._build_section("SIFT 方案", _SIFT_FIELDS, max_height=top_section_max_height),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        columns.addWidget(
            self._build_section("AI 方案", _AI_FIELDS, max_height=top_section_max_height),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        shell_layout.addLayout(columns)

        # ---- 通用设置（两列）+ 工具按钮（半宽）----
        bottom_cols = QHBoxLayout()
        bottom_cols.setSpacing(10)
        bottom_cols.addWidget(common_section, stretch=2)
        bottom_cols.addWidget(tools_section, stretch=1)
        shell_layout.addLayout(bottom_cols)
        shell_layout.addWidget(buttons_bar)

    def _build_section(
        self,
        title: str,
        fields: list[Field],
        *,
        max_height: int | None = None,
        two_columns: bool = False,
        narrow_editor: bool = False,
        extra_widget: QWidget | None = None,
    ) -> QFrame:
        """构建一个版块卡片。

        默认不套 QScrollArea —— 内容自然撑开 card 高度。
        设置 max_height 时，内容若超过该高度才包一个 QScrollArea 并按需显示滚动条。
        """
        card = QFrame()
        card.setObjectName("PanelCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 13px;")
        card_layout.addWidget(title_label)

        body = QWidget()
        if two_columns:
            outer = QHBoxLayout(body)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(18)
            for chunk in self._split_in_halves(fields):
                col = QVBoxLayout()
                col.setSpacing(10)
                for f in chunk:
                    col.addLayout(self._build_field(f, narrow_editor=narrow_editor))
                col.addStretch()
                outer.addLayout(col, stretch=1)
        else:
            form = QVBoxLayout(body)
            # # 底部留 8px 缓冲，避免最后一个字段的 wordwrap 说明行被滚动区裁掉
            form.setContentsMargins(0, 0, 0, 8)
            form.setSpacing(10)
            for f in fields:
                form.addLayout(self._build_field(f, narrow_editor=narrow_editor))

        if max_height is not None:
            natural = self._measure_body_height(
                body,
                self._estimate_top_section_body_width(),
            )
            if natural > max_height:
                body.setMinimumHeight(natural)

                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.NoFrame)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                scroll.viewport().setAutoFillBackground(False)
                scroll.setFixedHeight(max_height)
                scroll.setWidget(body)
                card_layout.addWidget(scroll)
                if extra_widget is not None:
                    card_layout.addWidget(extra_widget)
                return card

        card_layout.addWidget(body)
        if extra_widget is not None:
            card_layout.addWidget(extra_widget)
        return card

    def _compute_top_section_max_height(
        self,
        *,
        title_bar_height: int,
        bottom_row_height: int,
        button_row_height: int,
        shell_spacing: int,
    ) -> int:
        shell_available = (
            self._FIXED_HEIGHT
            - self._SHELL_TOP_MARGIN
            - self._SHELL_BOTTOM_MARGIN
        )
        top_row_total_height = (
            shell_available
            - title_bar_height
            - bottom_row_height
            - button_row_height
            - shell_spacing * 3
        )
        section_chrome = (
            self._SECTION_TOP_MARGIN
            + self._SECTION_BOTTOM_MARGIN
            + 8
            + self._section_title_height()
        )
        return max(160, top_row_total_height - section_chrome)

    def _section_title_height(self) -> int:
        probe = QLabel("X")
        probe.setObjectName("TitleLabel")
        probe.setStyleSheet("font-size: 13px;")
        return probe.sizeHint().height()

    def _estimate_top_section_body_width(self) -> int:
        shell_width = self._FIXED_WIDTH - self._SHELL_H_MARGIN * 2
        row_width = (shell_width - 10) // 2
        return max(160, row_width - self._SECTION_H_MARGIN * 2)

    @staticmethod
    def _measure_body_height(body: QWidget, width: int) -> int:
        layout = body.layout()
        if layout is None:
            return body.sizeHint().height()
        if layout.hasHeightForWidth():
            return layout.totalHeightForWidth(width)
        return max(layout.sizeHint().height(), body.sizeHint().height())

    @staticmethod
    def _split_in_halves(fields: list[Field]) -> list[list[Field]]:
        mid = (len(fields) + 1) // 2
        return [fields[:mid], fields[mid:]]

    def _build_minimap_row(self) -> QWidget:
        """构建通用设置底部的 "小地图区域" 行：按钮 + Top/Left/W/H 四个输入框。"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 6, 0)
        layout.setSpacing(8)

        label = QLabel("小地图")
        label.setStyleSheet(
            f"color: {theme.FG}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(label)

        set_btn = QPushButton("设置小地图")
        set_btn.setMinimumHeight(28)
        set_btn.clicked.connect(self._on_open_minimap_calibrator)
        layout.addWidget(set_btn)

        # 四个输入框：Top / Left / Width / Height
        self._minimap_editors: dict[str, QLineEdit] = {}
        raw = getattr(config, "MINIMAP", None) or {}
        for key, title in (("top", "Top"), ("left", "Left"),
                           ("width", "W"), ("height", "H")):
            lbl = QLabel(title)
            lbl.setObjectName("StatLabel")
            layout.addWidget(lbl)
            editor = QLineEdit()
            editor.setMinimumHeight(28)
            editor.setFixedWidth(60)
            editor.setAlignment(Qt.AlignRight)
            editor.setValidator(QIntValidator(-10_000, 10_000, editor))
            try:
                editor.setText(str(int(raw[key])))
            except (KeyError, TypeError, ValueError):
                editor.setText("")
            self._minimap_editors[key] = editor
            layout.addWidget(editor)
        layout.addStretch()
        return row

    def _on_open_minimap_calibrator(self) -> None:
        """打开基于 Qt 的小地图校准器；关闭后刷新四个输入框。"""
        from .minimap_selector import run_minimap_calibrator

        # 先关闭设置窗，避免两层 modal/非模态窗口的焦点问题。
        # 不传 parent 给校准器，让 overlay 成为独立顶层窗口，避免事件路由问题。
        self.hide()
        saved = run_minimap_calibrator(None)
        self.show()
        self.raise_()
        self.activateWindow()
        if saved:
            self._refresh_minimap_editors()
            # 立刻通知主窗口刷新缓存（不等用户点"应用"）
            self.applied.emit()
            toast(self, "小地图区域已更新")

    def _refresh_minimap_editors(self) -> None:
        raw = getattr(config, "MINIMAP", None) or {}
        for key, editor in self._minimap_editors.items():
            try:
                editor.setText(str(int(raw[key])))
            except (KeyError, TypeError, ValueError):
                editor.setText("")

    def _build_tools_section(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel("工具")
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 13px;")
        card_layout.addWidget(title_label)

        for name in _TOOL_BUTTONS:
            btn = QPushButton(name)
            btn.setMinimumHeight(30)
            btn.clicked.connect(
                lambda _=False, n=name: styled_info(
                    self, n, f"“{n}”功能尚未实现。"
                )
            )
            card_layout.addWidget(btn)
        card_layout.addStretch()
        return card

    def _build_field(self, f: Field, *, narrow_editor: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(8)

        # 左：参数名 + （范围·说明）
        left_wrap = QWidget()
        left_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        left = QVBoxLayout(left_wrap)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        label_text = f.label
        if f.needs_restart:
            label_text += "  ⟲"
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {theme.FG}; font-size: 12px; font-weight: 600;"
        )
        label.setWordWrap(True)
        if f.needs_restart:
            label.setToolTip("此参数需要重启应用才生效")
        left.addWidget(label)

        if f.value_range or f.desc:
            desc = QLabel(self._format_desc(f))
            desc.setObjectName("StatLabel")
            desc.setWordWrap(True)
            desc.setTextFormat(Qt.RichText)
            desc.setTextInteractionFlags(Qt.NoTextInteraction)
            # 允许垂直扩展以便换行时不被裁剪
            desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            left.addWidget(desc)

        # 右：输入框 —— narrow 时宽度减半 + 内边距收紧
        editor = QLineEdit(str(getattr(config, f.key, "")))
        editor.setMinimumHeight(28)
        editor.setFixedWidth(36 if narrow_editor else 72)
        if narrow_editor:
            editor.setStyleSheet("padding: 5px;")
        editor.setAlignment(Qt.AlignRight)
        if f.type_ is int:
            editor.setValidator(QIntValidator(-10_000_000, 10_000_000, editor))
        else:
            validator = QDoubleValidator(-1e9, 1e9, 4, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
        self._editors[f.key] = editor
        self._initial_values[f.key] = editor.text()
        left_wrap.setMinimumHeight(editor.minimumHeight())
        row.addWidget(left_wrap, stretch=1, alignment=Qt.AlignVCenter)
        row.addWidget(editor, alignment=Qt.AlignVCenter)
        return row

    @staticmethod
    def _format_desc(f: Field) -> str:
        """返回 '范围 · 说明' 的富文本，范围用高亮色。"""
        parts: list[str] = []
        if f.value_range:
            parts.append(
                f'<span style="color:{theme.ACCENT}; font-weight:600;">'
                f'{f.value_range}</span>'
            )
        if f.desc:
            parts.append(f.desc)
        return " · ".join(parts)

    # ---------- 数据收集 / 持久化 ----------

    def _collect(self) -> dict | None:
        result: dict = {}
        for f in _ALL_FIELDS:
            raw = self._editors[f.key].text().strip()
            if raw == "":
                continue
            try:
                result[f.key] = f.type_(raw) if f.type_ is int else float(raw)
            except ValueError:
                styled_info(
                    self, "输入无效",
                    f"字段 {f.label} 的值 “{raw}” 无法解析为 {f.type_.__name__}。"
                )
                return None

        # 小地图区域：四个输入框全部有效时才写入 MINIMAP
        minimap_payload: dict = {}
        for key, editor in getattr(self, "_minimap_editors", {}).items():
            raw = editor.text().strip()
            if raw == "":
                minimap_payload = {}
                break
            try:
                minimap_payload[key] = int(raw)
            except ValueError:
                styled_info(
                    self, "输入无效",
                    f"小地图 {key} 的值 “{raw}” 不是有效整数。",
                )
                return None
        if len(minimap_payload) == 4:
            # 和 config.py 中的 MINIMAP 结构一致
            result["MINIMAP"] = {
                "top": minimap_payload["top"],
                "left": minimap_payload["left"],
                "width": minimap_payload["width"],
                "height": minimap_payload["height"],
            }
        return result

    def _changed_restart_fields(self, values: dict) -> list[str]:
        changed: list[str] = []
        for key, new_val in values.items():
            field = _FIELD_INDEX.get(key)
            if field is None or not field.needs_restart:
                continue
            if str(new_val) != self._initial_values.get(key, ""):
                changed.append(field.label)
        return changed

    def _persist(self, values: dict) -> bool:
        try:
            config.save_config(values)
        except Exception as e:
            styled_info(self, "保存失败", f"写入 config.json 失败：{e}")
            return False
        self.applied.emit()
        # 刷新 initial_values，避免同一窗口再次点应用时重复弹重启提示
        for k, v in values.items():
            self._initial_values[k] = str(v)
        return True

    def _on_apply(self) -> None:
        values = self._collect()
        if values is None:
            return
        restart_fields = self._changed_restart_fields(values)
        if not self._persist(values):
            return
        if restart_fields:
            # 需要重启的改动仍然用常规提示框，让用户明确看清哪些参数待生效
            styled_info(
                self, "需要重启",
                "已保存，但以下参数需要重启应用后才会生效：\n\n  · " +
                "\n  · ".join(restart_fields),
            )
        else:
            toast(self, "设置已应用")

    def _on_apply_and_restart(self) -> None:
        values = self._collect()
        if values is None:
            return
        if not self._persist(values):
            return
        self.close()
        self.restart_requested.emit()

    def _on_reset_defaults(self) -> None:
        for f in _ALL_FIELDS:
            default_val = config.DEFAULT_CONFIG.get(f.key, "")
            self._editors[f.key].setText(str(default_val))

    # ---------- 无边框窗口：标题栏拖动 ----------

    def _is_on_title_bar(self, global_pos: QPoint) -> bool:
        if not hasattr(self, "_title_bar"):
            return False
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


# ============================================================
# 打开入口
# ============================================================
def _place_left_of(dlg: QDialog, anchor: QWidget) -> None:
    """把 dlg 放到 anchor 的左侧，右边紧贴 anchor 的左边。屏幕装不下就往右贴。"""
    anchor_geo = anchor.frameGeometry()
    screen = anchor.screen() if hasattr(anchor, "screen") else None
    avail = screen.availableGeometry() if screen is not None else None

    target_x = anchor_geo.left() - dlg.width()
    target_y = anchor_geo.top()

    if avail is not None:
        if target_x < avail.left():
            target_x = avail.left()
        target_y = max(avail.top(), min(target_y, avail.bottom() - dlg.height()))

    dlg.move(target_x, target_y)


def _restart_app() -> None:
    """重新用当前参数启动自身，然后退出当前进程。"""
    try:
        QApplication.quit()
    except Exception:
        pass
    python = sys.executable
    os.execl(python, python, *sys.argv)


# 单例引用，防止被 GC；非模态窗口关闭后会自动 deleteOnClose。
_active_dialog: SettingsDialog | None = None


def open_settings_dialog(
    parent,
    on_applied: Callable[[], None] | None = None,
) -> None:
    """非模态打开：不阻塞主窗口操作。重复点击会把已打开的窗口拉到前台。"""
    global _active_dialog
    if _active_dialog is not None:
        try:
            _active_dialog.raise_()
            _active_dialog.activateWindow()
            return
        except RuntimeError:
            _active_dialog = None

    dlg = SettingsDialog(parent)
    if on_applied is not None:
        dlg.applied.connect(on_applied)
    dlg.restart_requested.connect(_restart_app)

    def _clear_ref():
        global _active_dialog
        _active_dialog = None
    dlg.destroyed.connect(lambda _=None: _clear_ref())

    _active_dialog = dlg
    if parent is not None:
        _place_left_of(dlg, parent)
    dlg.show()
