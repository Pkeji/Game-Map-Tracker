"""Windows helpers for overlay-style tool windows."""
from __future__ import annotations

import sys

try:
    import ctypes

    _IS_WIN = sys.platform.startswith("win")
except Exception:  # pragma: no cover
    _IS_WIN = False


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


def _get_hwnd(qwidget) -> int | None:
    if not _IS_WIN:
        return None
    try:
        return int(qwidget.winId())
    except Exception:
        return None


def _set_style_bits(hwnd: int, bits: int, enabled: bool) -> None:
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= bits
    else:
        style &= ~bits
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def set_click_through(qwidget, enabled: bool) -> None:
    """Enable or disable mouse click-through."""
    if not _IS_WIN:
        return
    hwnd = _get_hwnd(qwidget)
    if hwnd is None:
        return
    _set_style_bits(hwnd, WS_EX_LAYERED, True)
    _set_style_bits(hwnd, WS_EX_TRANSPARENT, enabled)


def apply_overlay_flags(qwidget) -> None:
    """Keep the window hidden from Alt-Tab/taskbar without blocking focus."""
    if not _IS_WIN:
        return
    hwnd = _get_hwnd(qwidget)
    if hwnd is None:
        return
    _set_style_bits(hwnd, WS_EX_LAYERED | WS_EX_TOOLWINDOW, True)
