"""运行目录解析。

必须兼容 PyInstaller 的 ``--onefile``：那种模式下 ``__file__`` 指向临时解包
目录，进程一退出就被删掉，配置与状态文件绝不能写在那里。所以打包后一律以
``sys.executable``（也就是 exe 自己）所在的目录为准。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "etupirka2vnite"

# 数据源文件名（Etupirka 是绿色软件，user.db 与 Etupirka.exe 同级）
DB_FILENAME = "user.db"

_PROBE_NAME = ".etupirka2vnite-write-probe"

_CACHE: dict[str, object] = {}

__all__ = [
    "APP_NAME",
    "DB_FILENAME",
    "is_frozen",
    "app_dir",
    "data_dir",
    "uses_fallback_dir",
    "settings_file",
    "aliases_file",
    "progress_file",
    "default_export_dir",
    "error_log_file",
    "find_local_user_db",
    "reset_cache",
]


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的可执行文件里。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """程序所在目录。

    源码运行 = 工程根目录（``app/`` 的上一层）；打包后 = exe 所在目录。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(directory: Path) -> bool:
    probe = directory / _PROBE_NAME
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """配置与状态文件的存放目录。

    优先用程序所在目录；若不可写（例如被放进 ``C:\\Program Files``）则回退到
    ``%APPDATA%\\etupirka2vnite``。结果会缓存，重复调用不会反复探测磁盘。
    """
    cached = _CACHE.get("data_dir")
    if isinstance(cached, Path):
        return cached

    primary = app_dir()
    if primary.is_dir() and _writable(primary):
        resolved = primary
        fallback_used = False
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        resolved = Path(base) / APP_NAME
        resolved.mkdir(parents=True, exist_ok=True)
        fallback_used = True

    _CACHE["data_dir"] = resolved
    _CACHE["fallback"] = fallback_used
    return resolved


def uses_fallback_dir() -> bool:
    """配置是否落在了回退目录（界面据此提示用户实际位置）。"""
    data_dir()
    return bool(_CACHE.get("fallback"))


def settings_file() -> Path:
    return data_dir() / "settings.json"


def aliases_file() -> Path:
    return data_dir() / "aliases.json"


def progress_file() -> Path:
    return data_dir() / "progress.json"


def default_export_dir() -> Path:
    return data_dir() / "out"


def error_log_file() -> Path:
    """界面未捕获异常的落盘位置。"""
    return data_dir() / "error.log"


def find_local_user_db() -> Path | None:
    """探测「程序自己所在目录」里有没有 ``user.db``。

    这是首次启动的第二优先级数据源：把本工具直接丢进 Etupirka 文件夹即可开箱可用。
    """
    candidate = app_dir() / DB_FILENAME
    return candidate if candidate.is_file() else None


def reset_cache() -> None:
    """清空缓存。仅供测试使用。"""
    _CACHE.clear()
