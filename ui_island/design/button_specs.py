"""Shared button presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QPushButton


@dataclass(frozen=True)
class HeaderButtonSpec:
    text: str
    icon_text: str
    tooltip: str
    compact_width: int = 34


def apply_header_button_presentation(
    button: QPushButton,
    *,
    icon_only: bool,
    spec: HeaderButtonSpec,
) -> None:
    button.setToolTip(spec.tooltip)
    button.setMinimumHeight(26)
    button.setMaximumHeight(26)
    button.setProperty("headerIconOnly", icon_only)
    if icon_only:
        button.setText(spec.icon_text)
        button.setMinimumWidth(spec.compact_width)
        button.setMaximumWidth(spec.compact_width)
    else:
        button.setText(spec.text)
        button.setMinimumWidth(0)
        button.setMaximumWidth(16777215)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()
