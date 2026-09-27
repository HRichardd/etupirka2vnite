"""写 Windows 剪贴板。

用 ctypes 直接调 Win32 API，而不是 tkinter 的剪贴板。区别在于**数据所有权**：
``SetClipboardData`` 成功之后句柄归系统所有，本进程退出后内容依然在。
这样用户可以一次复制好几条，关掉工具再切到 Vnite 慢慢粘。

只读打开剪贴板时会重试几次——别的程序（输入法、剪贴板管理器）短暂占用是常态。
"""

from __future__ import annotations

import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

OPEN_ATTEMPTS = 8
OPEN_DELAY_SECONDS = 0.05


class ClipboardError(Exception):
    """带中文提示的剪贴板错误，可直接展示给用户。"""


if sys.platform == "win32":  # pragma: no cover - 平台分支
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = ctypes.c_void_p

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p


def available() -> bool:
    return sys.platform == "win32"


def _last_error(action: str) -> ClipboardError:
    import ctypes

    code = ctypes.get_last_error()
    try:
        detail = ctypes.FormatError(code).strip()
    except Exception:  # noqa: BLE001
        detail = ""
    if detail:
        return ClipboardError("%s失败（Win32 错误 %d：%s）" % (action, code, detail))
    return ClipboardError("%s失败（Win32 错误 %d）" % (action, code))


def _open() -> None:
    import ctypes

    for _ in range(OPEN_ATTEMPTS):
        if _user32.OpenClipboard(None):
            return
        time.sleep(OPEN_DELAY_SECONDS)
    raise _last_error("打开剪贴板（可能有别的程序正在占用，稍后再试）")


def copy_text(text: str) -> str:
    """把文本写入剪贴板。返回实际使用的通道名。

    抛出 :class:`ClipboardError` 表示失败，调用方应给出人工复制方案。
    """
    import ctypes

    if not text:
        raise ClipboardError("要复制的内容是空的。")
    if sys.platform != "win32":
        raise ClipboardError("当前系统不是 Windows，无法写入剪贴板。")

    data = (text + "\0").encode("utf-16-le")

    _open()
    try:
        if not _user32.EmptyClipboard():
            raise _last_error("清空剪贴板")

        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise _last_error("分配剪贴板内存")

        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            raise _last_error("锁定剪贴板内存")

        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            _kernel32.GlobalUnlock(handle)

        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            _kernel32.GlobalFree(handle)
            raise _last_error("写入剪贴板")

        # 成功：句柄所有权已交给系统，绝不能 GlobalFree
        return "win32"
    finally:
        _user32.CloseClipboard()


def read_text() -> str:
    """读回剪贴板文本。仅用于自检与「重试复制」的校验。"""
    import ctypes

    if sys.platform != "win32":
        raise ClipboardError("当前系统不是 Windows，无法读取剪贴板。")

    _open()
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            raise _last_error("读取剪贴板（剪贴板里可能不是文本）")

        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            raise _last_error("锁定剪贴板内存")
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()
