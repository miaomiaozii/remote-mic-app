"""Direct local control of WeChat Input Method's voice toolbar.

WeChat Input Method intentionally ignores synthetic ``Ctrl+Win`` events in
some foreground applications, even though its own toolbar remains available.
For the exact hold-to-talk preset, Remote Mic can click that toolbar's voice
button through its private window without moving the cursor or stealing focus.

The window class/title and owning executable are all verified before a click.
If any check fails, callers fall back to the configured keyboard shortcut.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from typing import Optional, Tuple


TOOLBAR_CLASS = "wetype.statusbar.window"
TOOLBAR_TITLE = "StatusBarWnd"
VOICE_WINDOW_CLASS = "wetype.flutter.setting"
VOICE_WINDOW_TITLE = "语音输入"
EXPECTED_PROCESS_NAME = "wetype_update.exe"

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _NativeWindows:
    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self.kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self.user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        self.user32.FindWindowW.restype = wintypes.HWND
        self.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetClientRect.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        )
        self.user32.GetClientRect.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.PostMessageW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def find_window(self, class_name: str, title: str) -> int:
        return int(self.user32.FindWindowW(class_name, title) or 0)

    def is_visible(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindowVisible(hwnd))

    def client_size(self, hwnd: int) -> Tuple[int, int]:
        rect = wintypes.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return (0, 0)
        return (max(0, rect.right - rect.left), max(0, rect.bottom - rect.top))

    def process_name(self, hwnd: int) -> str:
        pid = wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = self.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            self.kernel32.QueryFullProcessImageNameW.argtypes = (
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            )
            self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            if not self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(length)
            ):
                return ""
            return os.path.basename(buffer.value).lower()
        finally:
            self.kernel32.CloseHandle(handle)

    def post_left_click(self, hwnd: int, x: int, y: int) -> bool:
        lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
        down = bool(self.user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam))
        if not down:
            return False
        time.sleep(0.05)
        return bool(self.user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam))

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)


def voice_button_point(width: int, height: int) -> Tuple[int, int]:
    """Return the center of the second item in the five-item status bar."""

    return (max(1, int(width) * 3 // 10), max(1, int(height) // 2))


def set_voice_panel_active(
    active: bool,
    *,
    _native: Optional[object] = None,
    timeout_seconds: float = 0.75,
) -> bool:
    """Idempotently open or close WeChat Input Method's voice panel."""

    if _native is None:
        if sys.platform != "win32":
            return False
        native = _NativeWindows()
    else:
        native = _native

    toolbar = native.find_window(TOOLBAR_CLASS, TOOLBAR_TITLE)
    voice_window = native.find_window(VOICE_WINDOW_CLASS, VOICE_WINDOW_TITLE)
    if not toolbar or not voice_window or not native.is_visible(toolbar):
        return False
    if native.process_name(toolbar) != EXPECTED_PROCESS_NAME:
        return False

    desired = bool(active)
    if native.is_visible(voice_window) == desired:
        return True

    width, height = native.client_size(toolbar)
    if width <= 0 or height <= 0:
        return False
    x, y = voice_button_point(width, height)
    if not native.post_left_click(toolbar, x, y):
        return False

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() <= deadline:
        if native.is_visible(voice_window) == desired:
            return True
        native.sleep(0.01)
    return False
