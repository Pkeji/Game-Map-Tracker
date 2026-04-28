"""Hotkey listener management for island window."""

from __future__ import annotations

import time

import config

from ..services.hotkey_config import key_vk, modifier_names, native_modifier_flags

try:
    from pynput import keyboard
except ImportError:  # pragma: no cover
    keyboard = None


class HotkeyController:
    def __init__(self, window) -> None:
        self.window = window

    def start_listener(self) -> None:
        if self.window._is_windows and self.start_native_listener():
            return
        if keyboard is None:
            return

        required_modifiers = modifier_names(getattr(config, "TOGGLE_LOCK_HOTKEY", None))
        target_vk = key_vk(getattr(config, "TOGGLE_LOCK_HOTKEY", None))
        pressed_modifiers: set[str] = set()

        def on_press(key):
            modifier = self._pynput_modifier_name(key)
            if modifier is not None:
                pressed_modifiers.add(modifier)
                return
            if self._pynput_vk(key) != target_vk or not required_modifiers.issubset(pressed_modifiers):
                return
            self.request_toggle_lock()

        def on_release(key):
            modifier = self._pynput_modifier_name(key)
            if modifier is not None:
                pressed_modifiers.discard(modifier)

        self.window._hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.window._hotkey_listener.daemon = True
        self.window._hotkey_listener.start()

    def request_toggle_lock(self) -> None:
        if not self.window._can_toggle_lock():
            return
        now = time.monotonic()
        if now - self.window._last_hotkey_at < self.window._HOTKEY_DEBOUNCE_SEC:
            return
        self.window._last_hotkey_at = now
        self.window._toggle_lock_requested.emit()

    def start_native_listener(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes
            import threading
        except Exception:
            return False

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        wm_hotkey = 0x0312
        mod_norepeat = 0x4000
        hotkey = getattr(config, "TOGGLE_LOCK_HOTKEY", None)
        modifiers = native_modifier_flags(hotkey)
        vk = key_vk(hotkey)
        if not modifiers or not vk:
            return False

        def hotkey_loop():
            self.window._hotkey_thread_id = kernel32.GetCurrentThreadId()
            registered_hotkey = bool(
                user32.RegisterHotKey(
                    None,
                    self.window._NATIVE_HOTKEY_ID_ALT_GRAVE,
                    modifiers | mod_norepeat,
                    vk,
                )
            )
            if not registered_hotkey:
                self.window._hotkey_thread_id = None
                return

            message = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
                    if (
                        message.message == wm_hotkey
                        and message.wParam == self.window._NATIVE_HOTKEY_ID_ALT_GRAVE
                    ):
                        self.request_toggle_lock()
            finally:
                if registered_hotkey:
                    user32.UnregisterHotKey(None, self.window._NATIVE_HOTKEY_ID_ALT_GRAVE)
                self.window._hotkey_thread_id = None

        self.window._hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True)
        self.window._hotkey_thread.start()
        time.sleep(0.05)
        return self.window._hotkey_thread_id is not None

    @staticmethod
    def _pynput_vk(key) -> int | None:
        value = getattr(key, "vk", None)
        if value is not None:
            return int(value)
        nested = getattr(key, "value", None)
        value = getattr(nested, "vk", None)
        if value is not None:
            return int(value)
        return None

    @staticmethod
    def _pynput_modifier_name(key) -> str | None:
        if keyboard is None:
            return None
        if key in HotkeyController._pynput_keys("ctrl", "ctrl_l", "ctrl_r"):
            return "Ctrl"
        if key in HotkeyController._pynput_keys("alt", "alt_l", "alt_r"):
            return "Alt"
        if key in HotkeyController._pynput_keys("shift", "shift_l", "shift_r"):
            return "Shift"
        if key in HotkeyController._pynput_keys("cmd", "cmd_l", "cmd_r"):
            return "Meta"
        return None

    @staticmethod
    def _pynput_keys(*names: str) -> tuple:
        if keyboard is None:
            return ()
        return tuple(value for name in names if (value := getattr(keyboard.Key, name, None)) is not None)

    def stop_listener(self) -> None:
        if self.window._hotkey_listener is not None:
            self.window._hotkey_listener.stop()
            self.window._hotkey_listener = None

        if self.window._hotkey_thread_id is not None:
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(self.window._hotkey_thread_id, 0x0012, 0, 0)
            except Exception:
                pass

        if self.window._hotkey_thread is not None:
            self.window._hotkey_thread.join(timeout=0.5)
            self.window._hotkey_thread = None
