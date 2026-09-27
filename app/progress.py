"""已迁移状态的持久化。

按 uid 记录，所以换一个数据源不会串味。文件损坏时退化成「全部未迁移」——
宁可让用户重导一遍，也不能让一个状态文件把程序卡住。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Set

from .paths import progress_file

FORMAT_VERSION = 1


def _empty() -> Dict[str, Any]:
    return {"version": FORMAT_VERSION, "entries": {}}


def _clean(raw: Any) -> Dict[str, Any]:
    """把任意输入整理成规范结构，顺手丢掉垃圾。"""
    state = _empty()
    if not isinstance(raw, dict):
        return state

    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return state

    clean: Dict[str, Any] = {}
    for uid, value in entries.items():
        if not isinstance(uid, str) or not uid:
            continue
        when = ""
        if isinstance(value, dict):
            when = str(value.get("migrated_at") or "")
        clean[uid] = {"migrated_at": when}
    state["entries"] = clean
    return state


def load() -> Dict[str, Any]:
    """读取状态。任何异常都退化成空状态。"""
    try:
        raw = json.loads(progress_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    return _clean(raw)


def save(state: Dict[str, Any]) -> bool:
    """写回。失败返回 ``False``——界面会提示，但不该崩。"""
    payload = _clean(state)
    try:
        progress_file().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except OSError:
        return False


def migrated_uids(state: Dict[str, Any]) -> Set[str]:
    entries = state.get("entries")
    if not isinstance(entries, dict):
        return set()
    return {uid for uid in entries if isinstance(uid, str)}


def mark(state: Dict[str, Any], uid: str, when: str = "") -> Dict[str, Any]:
    """标记为已迁移。原地修改并返回。"""
    if not uid:
        return state

    entries = state.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        state["entries"] = entries

    entries[uid] = {
        "migrated_at": when or datetime.datetime.now().isoformat(timespec="seconds")
    }
    return state


def unmark(state: Dict[str, Any], uid: str) -> Dict[str, Any]:
    entries = state.get("entries")
    if isinstance(entries, dict):
        entries.pop(uid, None)
    return state


def migrated_at(state: Dict[str, Any], uid: str) -> str:
    entries = state.get("entries")
    if isinstance(entries, dict):
        record = entries.get(uid)
        if isinstance(record, dict):
            return str(record.get("migrated_at") or "")
    return ""
