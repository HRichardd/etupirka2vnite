"""生成 Vnite 的剪贴板导入载荷，并复刻 Vnite 的校验规则做自检。

格式是**严格两字段**的 JSON::

    {"timers":[{"start":"...","end":"..."}],
     "dailyPlayTimes":[{"date":"YYYY-MM-DD","playTime":<毫秒>}]}

Etupirka 只有「每天玩了多久」，没有起止时刻，所以 ``timers`` 恒为空数组，
全部时长落在 ``dailyPlayTimes``。Vnite 的 ``normalizeDailyPlayTimes`` 明确说明
日级记录不会被伪造成时间区间，因此不会污染它的小时分布图。

校验规则抄自 Vnite 源码
``renderer/src/components/Game/Config/ManageMenu/utils.ts`` 的
``parsePlayTimeClipboardData``：顶层恰好两个键、每个元素也恰好两个键、
日期要能被它的 ``parseLocalDate`` 解析、``playTime`` 必须是有限正数。
放行任何一条不合格的数据，用户粘进去都只会看到报错。
"""

from __future__ import annotations

import datetime
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .model import Entry

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TIMERS_KEY = "timers"
DAILY_KEY = "dailyPlayTimes"

#: Vnite 计算时会把单日封顶到 24 小时，我们只提醒、不替它改数据
MAX_DAILY_PLAYTIME_MS = 24 * 60 * 60 * 1000


@dataclass
class Validation:
    """自检结果。``errors`` 非空就绝不允许复制。"""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = list(self.errors) + list(self.warnings)
        return "；".join(parts)


def is_real_date(value: Any) -> bool:
    """严格的本地 ``YYYY-MM-DD``，而且必须是真实存在的日子。"""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return False
    return True


def build(entry: Entry) -> Dict[str, Any]:
    """把条目转成载荷。秒 → 毫秒。"""
    return {
        TIMERS_KEY: [],
        DAILY_KEY: [
            {"date": day.date, "playTime": int(day.seconds) * 1000} for day in entry.days
        ],
    }


def dumps(payload: Dict[str, Any]) -> str:
    """紧凑 JSON，粘贴用。不含中日文，但仍用 UTF-8 友好写法。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def validate(payload: Any) -> Validation:
    """按 Vnite 的规则自检。"""
    result = Validation()

    if not isinstance(payload, dict):
        result.errors.append("载荷不是一个 JSON 对象")
        return result
    if len(payload) != 2 or TIMERS_KEY not in payload or DAILY_KEY not in payload:
        result.errors.append("顶层必须恰好包含 timers 与 dailyPlayTimes 两个键")
        return result

    timers = payload[TIMERS_KEY]
    daily = payload[DAILY_KEY]
    if not isinstance(timers, list):
        result.errors.append("timers 必须是数组")
    if not isinstance(daily, list):
        result.errors.append("dailyPlayTimes 必须是数组")
    if result.errors:
        return result

    for index, timer in enumerate(timers, 1):
        if not isinstance(timer, dict) or len(timer) != 2 or set(timer) != {"start", "end"}:
            result.errors.append("第 %d 个 timer 必须恰好包含 start 与 end" % index)
            continue
        for key in ("start", "end"):
            value = timer[key]
            if not isinstance(value, str) or not _parsable(value):
                result.errors.append("第 %d 个 timer 的 %s 不是合法时间" % (index, key))

    seen: Dict[str, int] = {}
    for index, item in enumerate(daily, 1):
        if not isinstance(item, dict) or len(item) != 2 or set(item) != {"date", "playTime"}:
            result.errors.append("第 %d 条日记录必须恰好包含 date 与 playTime" % index)
            continue

        date = item["date"]
        play_time = item["playTime"]

        if not is_real_date(date):
            result.errors.append("第 %d 条日期 %r 不是合法的 YYYY-MM-DD" % (index, date))
            continue
        if (
            isinstance(play_time, bool)
            or not isinstance(play_time, (int, float))
            or not math.isfinite(play_time)
            or play_time <= 0
        ):
            result.errors.append(
                "第 %d 条（%s）的时长必须是正数毫秒，实际是 %r" % (index, date, play_time)
            )
            continue

        if date in seen:
            result.errors.append("日期 %s 重复出现" % date)
        seen[date] = play_time

        if play_time > MAX_DAILY_PLAYTIME_MS:
            result.warnings.append(
                "%s 单日 %.1f 小时，Vnite 计算时会封顶到 24 小时"
                % (date, play_time / 3600000.0)
            )

    if not daily:
        result.warnings.append("这条没有任何日记录，导入后不会改变 Vnite 里的时长")

    return result


def _parsable(value: str) -> bool:
    """近似 JavaScript 的 ``Date.parse``：能被解析出时间即可。"""
    text = value.strip()
    if not text:
        return False
    candidate = text.replace("Z", "+00:00")
    try:
        datetime.datetime.fromisoformat(candidate)
        return True
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            datetime.datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def prepare(entry: Entry) -> Tuple[str, Validation]:
    """一步得到「要粘贴的字符串」和「自检结果」。"""
    payload = build(entry)
    return dumps(payload), validate(payload)
