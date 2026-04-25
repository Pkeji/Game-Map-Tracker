"""Settings dialog and styled prompt helpers for island UI."""

from __future__ import annotations

import os
import sys
from typing import Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config

from . import StyledConfirm, StyledMessage, center_dialog, place_left_of, toast
from ..design import qss, strings, tokens
from ..services.settings_schema import ALL_FIELDS, COMMON_FIELDS, FIELD_INDEX, SIFT_FIELDS, TOOL_BUTTONS, Field
from ..widgets.factory import make_scroll_area


def styled_info(parent, title: str, message: str) -> None:
    dialog = StyledMessage(parent, title, message)
    center_dialog(dialog, parent)
    dialog.exec()


def styled_confirm(
    parent,
    title: str,
    message: str,
    confirm_text: str = "确定",
    cancel_text: str = "取消",
) -> bool:
    dialog = StyledConfirm(parent, title, message, confirm_text=confirm_text, cancel_text=cancel_text)
    center_dialog(dialog, parent)
    return dialog.exec() == QDialog.Accepted


class SettingsDialog(QDialog):
    applied = Signal()
    restart_requested = Signal()
    annotation_refresh_requested = Signal()

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
        qss.ensure_tooltip_style()
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.resize(self._FIXED_WIDTH, self._FIXED_HEIGHT)

        self._drag_offset: QPoint | None = None
        self._editors: dict[str, QLineEdit] = {}
        self._initial_values: dict[str, str] = {}
        self._minimap_editors: dict[str, QLineEdit] = {}
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

        subtitle = QLabel("修改后点击“应用”写回 config.json；标记 ⟲ 的参数需重启才生效。")
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
        tools_section = self._build_tools_section()

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

        common_probe = self._build_section(
            "通用设置",
            COMMON_FIELDS,
            two_columns=True,
            narrow_editor=True,
            extra_widget=minimap_row,
            extra_widget_position="top",
        )
        top_section_max_height = self._compute_top_section_max_height(
            title_bar_height=title_bar.sizeHint().height(),
            bottom_row_height=max(
                common_probe.sizeHint().height(),
                tools_section.sizeHint().height(),
            ),
            button_row_height=buttons_bar.sizeHint().height(),
            shell_spacing=shell_layout.spacing(),
        )
        common_section = self._build_section(
            "通用设置",
            COMMON_FIELDS,
            max_height=top_section_max_height,
            two_columns=True,
            narrow_editor=True,
            extra_widget=minimap_row,
            extra_widget_position="top",
        )

        columns = QHBoxLayout()
        columns.setSpacing(10)
        columns.addWidget(
            self._build_section("SIFT 方案", SIFT_FIELDS, max_height=top_section_max_height),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        columns.addWidget(
            self._build_message_section("AI 方案", strings.SETTINGS_AI_DISABLED_MESSAGE),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        shell_layout.addLayout(columns)

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
        extra_widget_position: str = "bottom",
    ) -> QFrame:
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
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 8)
        body_layout.setSpacing(10)
        if extra_widget is not None and extra_widget_position == "top":
            body_layout.addWidget(extra_widget)

        fields_body = QWidget(body)
        if two_columns:
            outer = QHBoxLayout(fields_body)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(18)
            for chunk in self._split_in_halves(fields):
                col = QVBoxLayout()
                col.setSpacing(10)
                for field in chunk:
                    col.addLayout(self._build_field(field, narrow_editor=narrow_editor))
                col.addStretch()
                outer.addLayout(col, stretch=1)
        else:
            form = QVBoxLayout(fields_body)
            form.setContentsMargins(0, 0, 0, 8)
            form.setSpacing(10)
            for field in fields:
                form.addLayout(self._build_field(field, narrow_editor=narrow_editor))

        body_layout.addWidget(fields_body)
        if extra_widget is not None and extra_widget_position != "top":
            body_layout.addWidget(extra_widget)

        if max_height is not None:
            natural = self._measure_body_height(body, self._estimate_top_section_body_width())
            if natural > max_height:
                body.setMinimumHeight(natural)
                scroll = make_scroll_area(
                    horizontal_policy=Qt.ScrollBarAlwaysOff,
                    vertical_policy=Qt.ScrollBarAsNeeded,
                    fixed_height=max_height,
                )
                scroll.setWidget(body)
                card_layout.addWidget(scroll)
                return card

        card_layout.addWidget(body)
        return card

    def _build_message_section(self, title: str, message: str) -> QFrame:
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

        body = QLabel(message)
        body.setObjectName("StatLabel")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        card_layout.addWidget(body)
        card_layout.addStretch(1)
        return card

    def _compute_top_section_max_height(
        self,
        *,
        title_bar_height: int,
        bottom_row_height: int,
        button_row_height: int,
        shell_spacing: int,
    ) -> int:
        shell_available = self._FIXED_HEIGHT - self._SHELL_TOP_MARGIN - self._SHELL_BOTTOM_MARGIN
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
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 6, 0)
        layout.setSpacing(8)

        label = QLabel("小地图")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        minimap_control_height = 26

        set_btn = QPushButton("设置小地图")
        set_btn.setFixedHeight(minimap_control_height)
        set_btn.clicked.connect(self._on_open_minimap_calibrator)
        layout.addWidget(set_btn)

        raw = getattr(config, "MINIMAP", None) or {}
        for key, title in (("top", "Top"), ("left", "Left"), ("width", "W"), ("height", "H")):
            lbl = QLabel(title)
            lbl.setObjectName("StatLabel")
            layout.addWidget(lbl)
            editor = QLineEdit()
            editor.setFixedHeight(minimap_control_height)
            editor.setFixedWidth(60)
            editor.setStyleSheet("padding: 2px 6px;")
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
        from .minimap_selector import run_minimap_calibrator

        self.hide()
        saved = run_minimap_calibrator(None)
        self.show()
        self.raise_()
        self.activateWindow()
        if saved:
            self._refresh_minimap_editors()
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

        for name in TOOL_BUTTONS:
            btn = QPushButton(name)
            btn.setMinimumHeight(30)
            if name == strings.ANNOTATION_REFRESH_POINTS:
                btn.setToolTip(strings.ANNOTATION_REFRESH_POINTS_TOOLTIP)
                btn.clicked.connect(self.annotation_refresh_requested.emit)
            else:
                btn.clicked.connect(
                    lambda _=False, n=name: styled_info(self, n, f"“{n}”功能尚未实现。")
                )
            card_layout.addWidget(btn)
        card_layout.addStretch()
        return card

    def _build_field(self, field: Field, *, narrow_editor: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(8)

        left_wrap = QWidget()
        left_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        left = QVBoxLayout(left_wrap)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)

        label_text = field.label
        if field.needs_restart:
            label_text += "  ⟲"
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        label.setWordWrap(True)
        if field.needs_restart:
            label.setToolTip("此参数需要重启应用后才生效")
        left.addWidget(label)

        if field.value_range or field.desc:
            desc = QLabel(self._format_desc(field))
            desc.setObjectName("StatLabel")
            desc.setWordWrap(True)
            desc.setTextFormat(Qt.RichText)
            desc.setTextInteractionFlags(Qt.NoTextInteraction)
            desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            left.addWidget(desc)

        editor = QLineEdit(str(getattr(config, field.key, "")))
        editor.setMinimumHeight(28)
        editor.setFixedWidth(36 if narrow_editor else 72)
        if narrow_editor:
            editor.setStyleSheet("padding: 5px;")
        editor.setAlignment(Qt.AlignRight)
        if field.type_ is int:
            editor.setValidator(QIntValidator(-10_000_000, 10_000_000, editor))
        else:
            validator = QDoubleValidator(-1e9, 1e9, 4, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
        self._editors[field.key] = editor
        self._initial_values[field.key] = editor.text()
        left_wrap.setMinimumHeight(editor.minimumHeight())
        row.addWidget(left_wrap, stretch=1, alignment=Qt.AlignVCenter)
        row.addWidget(editor, alignment=Qt.AlignVCenter)
        return row

    @staticmethod
    def _format_desc(field: Field) -> str:
        parts: list[str] = []
        if field.value_range:
            parts.append(f'<span style="color:{tokens.ACCENT}; font-weight:600;">{field.value_range}</span>')
        if field.desc:
            parts.append(field.desc)
        return " · ".join(parts)

    def _collect(self) -> dict | None:
        result: dict = {}
        for field in ALL_FIELDS:
            editor = self._editors.get(field.key)
            if editor is None:
                continue
            raw = editor.text().strip()
            if raw == "":
                continue
            try:
                result[field.key] = field.type_(raw) if field.type_ is int else float(raw)
            except ValueError:
                styled_info(
                    self,
                    "输入无效",
                    f"字段 {field.label} 的值“{raw}”无法解析为 {field.type_.__name__}。",
                )
                return None

        minimap_payload: dict = {}
        for key, editor in self._minimap_editors.items():
            raw = editor.text().strip()
            if raw == "":
                minimap_payload = {}
                break
            try:
                minimap_payload[key] = int(raw)
            except ValueError:
                styled_info(self, "输入无效", f"小地图 {key} 的值“{raw}”不是有效整数。")
                return None
        if len(minimap_payload) == 4:
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
            field = FIELD_INDEX.get(key)
            if field is None or not field.needs_restart:
                continue
            if str(new_val) != self._initial_values.get(key, ""):
                changed.append(field.label)
        return changed

    def _persist(self, values: dict) -> bool:
        try:
            config.save_config(values)
        except Exception as exc:
            styled_info(self, "保存失败", f"写入 config.json 失败：{exc}")
            return False
        self.applied.emit()
        for key, value in values.items():
            self._initial_values[key] = str(value)
        return True

    def _on_apply(self) -> None:
        values = self._collect()
        if values is None:
            return
        restart_fields = self._changed_restart_fields(values)
        if not self._persist(values):
            return
        if restart_fields:
            styled_info(
                self,
                "需要重启",
                "已保存，但以下参数需要重启应用后才会生效：\n\n  " + "\n  ".join(restart_fields),
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
        for field in ALL_FIELDS:
            editor = self._editors.get(field.key)
            if editor is None:
                continue
            default_val = config.DEFAULT_CONFIG.get(field.key, "")
            editor.setText(str(default_val))

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


def _restart_app() -> None:
    try:
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception:
        pass
    python = sys.executable
    os.execl(python, python, *sys.argv)


_active_dialog: SettingsDialog | None = None


def open_settings_dialog(
    parent,
    on_applied: Callable[[], None] | None = None,
    on_closed: Callable[[], None] | None = None,
    on_annotation_refresh_requested: Callable[[], None] | None = None,
) -> None:
    global _active_dialog
    if _active_dialog is not None:
        try:
            _active_dialog.raise_()
            _active_dialog.activateWindow()
            return
        except RuntimeError:
            _active_dialog = None

    dialog = SettingsDialog(parent)
    if on_applied is not None:
        dialog.applied.connect(on_applied)
    if on_annotation_refresh_requested is not None:
        dialog.annotation_refresh_requested.connect(on_annotation_refresh_requested)
    dialog.restart_requested.connect(_restart_app)

    def _clear_ref():
        global _active_dialog
        _active_dialog = None
        if on_closed is not None:
            on_closed()

    dialog.destroyed.connect(lambda _=None: _clear_ref())
    _active_dialog = dialog
    if parent is not None:
        place_left_of(dialog, parent)
    dialog.show()


def close_active_settings_dialog() -> bool:
    global _active_dialog
    if _active_dialog is None:
        return False
    try:
        _active_dialog.close()
        return True
    except RuntimeError:
        _active_dialog = None
        return False


def has_active_settings_dialog() -> bool:
    return _active_dialog is not None
