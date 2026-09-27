"""记住的数据源与界面偏好。

存在程序所在目录（不可写时回退 ``%APPDATA%``，见 :mod:`app.paths`）。
文件损坏或格式不对时一律退回默认值——绝不能因为一个配置文件让程序起不来。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .paths import settings_file

#: 「最近 ▾」下拉保留几个路径
MAX_RECENT = 5

DEFAULTS: Dict[str, Any] = {
    "db_path": "",  # 上次用的数据源（目录或 user.db 的完整路径）
    "recent": [],  # 最近用过的数据源，最新的在最前
    "export_dir": "",  # 上次导出到的目录
}


def _clean_recent(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in result:
            result.append(item)
    return result[:MAX_RECENT]


def load() -> Dict[str, Any]:
    """读取设置。任何异常都退化成默认值。"""
    data: Dict[str, Any] = dict(DEFAULTS)
    data["recent"] = []

    try:
        raw = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data

    if not isinstance(raw, dict):
        return data

    data["db_path"] = str(raw.get("db_path") or "")
    data["export_dir"] = str(raw.get("export_dir") or "")
    data["recent"] = _clean_recent(raw.get("recent"))
    return data


def save(data: Dict[str, Any]) -> bool:
    """写回设置。失败返回 ``False``——调用方可以提示，但不该崩。"""
    payload = {
        "db_path": str(data.get("db_path") or ""),
        "recent": _clean_recent(data.get("recent")),
        "export_dir": str(data.get("export_dir") or ""),
    }
    try:
        settings_file().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except OSError:
        return False


def remember_db(data: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    """把这次用的路径挪到「最近」最前面，去重并截断。原地修改并返回。"""
    path = str(db_path)
    recent = [item for item in _clean_recent(data.get("recent")) if item != path]
    recent.insert(0, path)
    data["recent"] = recent[:MAX_RECENT]
    data["db_path"] = path
    return data
