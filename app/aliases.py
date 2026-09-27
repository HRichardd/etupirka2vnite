"""别名表：uid → 用户给这条记录起的名字。

刻意放在导出目录**之外**。导出时只覆盖 `out/` 里自己生成的那几个文件，
绝不会因为「重新导出」把用户辛苦起的名字清掉。

**别名优先于 `games.title`**：显式重命名是用户的明确意图，应当能盖过从
Etupirka 读来的原标题（那可能被列宽截断，例如「ガマンができない童貞兄キと、
スナオになれない反抗妹」）。对未识别条目来说，「覆盖」与「兜底」是同一件事，
所以这条规则只是让已识别条目也能被修正。
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .paths import aliases_file

FORMAT_VERSION = 1


def _empty() -> Dict[str, Any]:
    return {"version": FORMAT_VERSION, "aliases": {}}


def _clean(raw: Any) -> Dict[str, Any]:
    """整理成规范结构，顺手丢掉空白名和非字符串。"""
    state = _empty()
    if not isinstance(raw, dict):
        return state

    aliases = raw.get("aliases")
    if not isinstance(aliases, dict):
        return state

    clean: Dict[str, str] = {}
    for uid, name in aliases.items():
        if not isinstance(uid, str) or not uid:
            continue
        if not isinstance(name, str):
            continue
        name = name.strip()
        if name:
            clean[uid] = name
    state["aliases"] = clean
    return state


def load() -> Dict[str, Any]:
    """读取别名表。文件缺失或损坏都退化成空表。"""
    try:
        raw = json.loads(aliases_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    return _clean(raw)


def save(state: Dict[str, Any]) -> bool:
    """写回。失败返回 ``False``——界面会提示，但不该崩。"""
    payload = _clean(state)
    try:
        aliases_file().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except OSError:
        return False


def mapping(state: Dict[str, Any]) -> Dict[str, str]:
    """取出 ``uid → 名字`` 的普通字典，给读取层用。"""
    aliases = state.get("aliases")
    return dict(aliases) if isinstance(aliases, dict) else {}


def get(state: Dict[str, Any], uid: str, default: str = "") -> str:
    return mapping(state).get(uid, default)


def set_alias(state: Dict[str, Any], uid: str, name: str) -> Dict[str, Any]:
    """起名。``name`` 去掉空白后为空，等同于删掉这条别名。"""
    if not uid:
        return state

    name = (name or "").strip()
    if not name:
        return remove_alias(state, uid)

    aliases = state.get("aliases")
    if not isinstance(aliases, dict):
        aliases = {}
        state["aliases"] = aliases
    aliases[uid] = name
    return state


def remove_alias(state: Dict[str, Any], uid: str) -> Dict[str, Any]:
    aliases = state.get("aliases")
    if isinstance(aliases, dict):
        aliases.pop(uid, None)
    return state


def count(state: Dict[str, Any]) -> int:
    return len(mapping(state))
