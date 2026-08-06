"""Explicit UAC launcher for the narrowly scoped RC001/RC003 HID tap.

The normal settings and bridge processes remain unelevated.  Only a direct
user click invokes this helper, which asks Windows to start a short-lived copy
of the same signed/built application in ``--rc003-hid-injector`` mode.  That
mode independently re-discovers and validates the exact RC001/RC003 WUDF host,
verifies the pinned Gadget hash, loads it, and exits.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

from .frida_hid_tap_runtime import find_rc003_hidogatt_host_pid


SW_HIDE = 0
SHELL_SUCCESS_MINIMUM = 32
SHELL_ACCESS_DENIED = 5


class HidTapActivationError(RuntimeError):
    pass


class HidTapActivationCancelled(HidTapActivationError):
    pass


def build_activation_command(
    pid: int,
    *,
    frozen: bool | None = None,
    executable: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(executable, parameters, working_directory)`` for UAC."""

    if pid <= 0:
        raise HidTapActivationError("未找到有效的 RC001/RC003 HID 服务进程。")
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if executable is None:
        executable = sys.executable
    if not executable:
        raise HidTapActivationError("当前程序路径为空，无法启动 HID 支持助手。")
    arguments = ["--rc003-hid-injector", "--pid", str(pid)]
    if not frozen:
        arguments = ["-m", "ovb_rc003", *arguments]
    return executable, subprocess.list2cmdline(arguments), str(Path(executable).parent)


def _shell_execute(
    executable: str,
    parameters: str,
    working_directory: str,
) -> int:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = (
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    )
    shell32.ShellExecuteW.restype = wintypes.HINSTANCE
    result = shell32.ShellExecuteW(
        None,
        "runas",
        executable,
        parameters,
        working_directory,
        SW_HIDE,
    )
    return int(ctypes.cast(result, ctypes.c_void_p).value or 0)


def request_hid_tap_activation(
    *,
    _find_pid: Callable[[], int | None] = find_rc003_hidogatt_host_pid,
    _launch: Callable[[str, str, str], int] = _shell_execute,
) -> int:
    """Ask for UAC only after an explicit UI action and return the target PID."""

    if os.name != "nt":
        raise HidTapActivationError("完整 HID 支持只适用于 Windows。")
    pid = _find_pid()
    if pid is None:
        raise HidTapActivationError(
            "未找到 RC001/RC003 HID 服务。请先在 Windows 蓝牙设置中连接遥控器。"
        )
    executable, parameters, working_directory = build_activation_command(pid)
    result = _launch(executable, parameters, working_directory)
    if result <= SHELL_SUCCESS_MINIMUM:
        if result == SHELL_ACCESS_DENIED:
            raise HidTapActivationCancelled("已取消管理员授权，未启用返回键支持。")
        raise HidTapActivationError(f"无法启动 HID 支持助手（Windows 错误 {result}）。")
    return pid
