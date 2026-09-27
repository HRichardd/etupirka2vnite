"""中间数据模型：Etupirka 的条目在内存里的统一表示。

这一层刻意不依赖 sqlite3 也不依赖 tkinter，方便单独测试，
也让「读数据」和「画界面」彻底解耦。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

# ---- 条目标记 ----

FLAG_UNIDENTIFIED = "unidentified"
"""games 表里查不到、也没有别名 → 界面显示为「未识别-NN」。"""

FLAG_NO_PLAYTIME = "no_playtime"
"""games 表里有这个游戏，但一条游玩记录都没有。"""

FLAG_OVER_24H = "over_24h"
"""存在单日超过 24 小时的记录（Vnite 计算时会封顶到 24h）。"""

FLAG_TOTAL_MISMATCH = "total_mismatch"
"""每日记录之和与 gametimeinfo.playtime 相差超过容差。"""

UNIDENTIFIED_LABEL = "未识别-%02d"

MAX_DAY_SECONDS = 24 * 3600

#: 给人看的标记说明。界面与导出报告共用，免得两处措辞对不上。
FLAG_LABELS = {
    FLAG_UNIDENTIFIED: "未识别",
    FLAG_NO_PLAYTIME: "没有任何游玩记录",
    FLAG_OVER_24H: "存在单日超过 24 小时的记录",
    FLAG_TOTAL_MISMATCH: "与 gametimeinfo 的总时长不一致",
}


@dataclass(frozen=True)
class Day:
    """某一天的游玩时长。Etupirka 只有日级精度，没有起止时刻。"""

    date: str  # YYYY-MM-DD
    seconds: int


@dataclass
class Entry:
    """一个游戏条目（对应 Etupirka 的一个 uid）。"""

    uid: str
    title: str = ""
    title_source: str = ""  # "user.db" / "alias" / ""
    days: List[Day] = field(default_factory=list)
    brand: str = ""
    saleday: str = ""
    esid: int = -1
    exec_path: str = ""
    proc_path: str = ""
    firstplay: str = ""
    lastplay: str = ""
    label: str = ""  # 显示名，由 label_entries() 填
    flags: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> int:
        return sum(day.seconds for day in self.days)

    @property
    def identified(self) -> bool:
        return bool(self.title)

    @property
    def first(self) -> str:
        return min(day.date for day in self.days) if self.days else ""

    @property
    def last(self) -> str:
        return max(day.date for day in self.days) if self.days else ""

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags


@dataclass
class LoadResult:
    """一次完整的读取结果。"""

    path: Path
    entries: List[Entry] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> int:
        return sum(entry.total_seconds for entry in self.entries)

    @property
    def identified_count(self) -> int:
        return sum(1 for entry in self.entries if entry.identified)

    @property
    def unidentified_count(self) -> int:
        return sum(1 for entry in self.entries if not entry.identified)


def label_entries(entries: Iterable[Entry]) -> List[Entry]:
    """给条目分配显示名。

    已识别的直接用游戏名；未识别的按出现顺序编号成 ``未识别-01``、``未识别-02``……
    编号只取决于传入顺序，因此调用方必须先排好序再调用。
    """
    counter = 0
    result: List[Entry] = []
    for entry in entries:
        if entry.identified:
            entry.label = entry.title
        else:
            counter += 1
            entry.label = UNIDENTIFIED_LABEL % counter
            if FLAG_UNIDENTIFIED not in entry.flags:
                entry.flags.append(FLAG_UNIDENTIFIED)
        result.append(entry)
    return result


def format_duration(seconds: int) -> str:
    """把秒数格式化成人看的「N 小时 M 分」。"""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return "%d 小时 %d 分" % (hours, minutes)
    return "%d 分" % minutes
