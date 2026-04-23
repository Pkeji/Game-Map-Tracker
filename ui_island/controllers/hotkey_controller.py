"""Hotkey listener management for island window."""

from __future__ import annotations

import time

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

        def on_press(key):
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self.window._alt_pressed = True
                return
            if getattr(key, "vk", None) != 0xC0 or not self.window._alt_pressed:
                return
            self.request_toggle_lock()

        def on_release(key):
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self.window._alt_pressed = False

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
        mod_alt = 0x0001
        mod_norepeat = 0x4000
        vk_oem_3 = 0xC0

        def hotkey_loop():
            self.window._hotkey_thread_id = kernel32.GetCurrentThreadId()
            registered_hotkey = bool(
                user32.RegisterHotKey(
                    None,
                    self.window._NATIVE_HOTKEY_ID_ALT_GRAVE,
                    mod_alt | mod_norepeat,
                    vk_oem_3,
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
