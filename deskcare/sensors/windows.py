"""Bounded Windows activity provider for M1.

Only idle duration and a coarse application category are returned. The
provider never reads keyboard content, window titles, URLs, clipboard data or
document names. On non-Windows systems construction fails explicitly so the
application can use its labelled FakeProvider instead.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from datetime import datetime
from pathlib import PureWindowsPath
from time import monotonic

from deskcare.domain.types import ActivityKind, ActivitySample


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_CATEGORY_MAP = {
    "code": "CODE",
    "code - insiders": "CODE",
    "pycharm": "CODE",
    "idea": "CODE",
    "devenv": "CODE",
    "chrome": "BROWSER",
    "msedge": "BROWSER",
    "firefox": "BROWSER",
    "brave": "BROWSER",
    "qq": "MEETING",
    "weixin": "MEETING",
    "tim": "MEETING",
    "teams": "MEETING",
    "zoom": "MEETING",
    "winword": "OFFICE",
    "excel": "OFFICE",
    "powerpnt": "OFFICE",
    "wps": "OFFICE",
}


def _tick_delta_ms(current_tick64: int, last_input_tick32: int) -> int:
    """Calculate a GetLastInputInfo delta across the 32-bit tick wrap."""

    delta = (int(current_tick64) & 0xFFFFFFFF) - (int(last_input_tick32) & 0xFFFFFFFF)
    return delta if delta >= 0 else delta + (1 << 32)


def _category_for_executable(executable: str | None) -> str:
    if not executable:
        return "UNKNOWN"
    stem = PureWindowsPath(executable).stem.casefold()
    return _CATEGORY_MAP.get(stem, "OTHER")


class WindowsActivityProvider:
    """Read one bounded sample from supported Win32 APIs."""

    is_demo = False

    def __init__(self, idle_threshold_s: float = 60.0, include_category: bool = True) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsActivityProvider is available only on Windows")
        self.idle_threshold_s = float(idle_threshold_s)
        self.include_category = include_category
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        self._user32.GetLastInputInfo.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._last_category: str | None = None

    def _idle_seconds(self) -> float:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        elapsed_ms = _tick_delta_ms(int(self._kernel32.GetTickCount64()), int(info.dwTime))
        return max(0.0, elapsed_ms / 1000.0)

    def _foreground_executable(self) -> str | None:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = self._kernel32.OpenProcess(0x1000 | 0x0400, False, pid.value)
        if not process:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self._kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            ):
                return buffer.value
            return None
        finally:
            self._kernel32.CloseHandle(process)

    def read_sample(self) -> ActivitySample:
        idle_s = self._idle_seconds()
        category = _category_for_executable(self._foreground_executable()) if self.include_category else None
        changed = self._last_category is not None and category != self._last_category
        self._last_category = category
        state = ActivityKind.IDLE if idle_s >= self.idle_threshold_s else ActivityKind.ACTIVE
        return ActivitySample(
            monotonic_s=monotonic(),
            wall_time=datetime.now().astimezone(),
            idle_s=idle_s,
            app_category=category,
            state=state,
            is_foreground_change=changed,
            observation_ok=True,
        )
