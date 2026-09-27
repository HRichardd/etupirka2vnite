"""导出迁移资料：汇总 CSV、逐日明细 CSV、原始 JSON、可读报告。

**只覆盖自己生成的那四个文件名**，绝不整目录删除——`out/` 里可能还放着用户
自己的截图或笔记。CSV 用 ``utf-8-sig``，Excel 双击打开不乱码。
"""

from __future__ import annotations

import csv
import datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .model import FLAG_LABELS, Entry, LoadResult, format_duration

SUMMARY_NAME = "etupirka-汇总.csv"
DAILY_NAME = "etupirka-每日明细.csv"
RAW_NAME = "etupirka-raw.json"
REPORT_NAME = "report.txt"

#: 本工具会生成（也只会覆盖）的文件
GENERATED_FILES = (SUMMARY_NAME, DAILY_NAME, RAW_NAME, REPORT_NAME)


class ExportError(Exception):
    """带中文提示的导出错误。"""


def _guard(path: Path, writer) -> Path:
    try:
        writer()
    except OSError as exc:
        raise ExportError(
            "写入 %s 失败：%s" % (path.name, exc.strerror or exc)
        ) from exc
    return path


def _remark(entry: Entry, migrated: Set[str]) -> str:
    parts: List[str] = []
    if entry.title_source == "alias":
        parts.append("游戏名来自别名表")
    parts.extend(FLAG_LABELS.get(flag, flag) for flag in entry.flags)
    if entry.uid in migrated:
        parts.append("已迁移")
    return "；".join(parts)


def write_summary_csv(
    path: Path, result: LoadResult, migrated: Optional[Set[str]] = None
) -> Path:
    migrated = migrated or set()

    def run() -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "游戏名",
                    "条目ID(uid)",
                    "总时长(秒)",
                    "总时长(小时)",
                    "有记录天数",
                    "首次游玩",
                    "最后游玩",
                    "启动程序",
                    "状态",
                    "备注",
                ]
            )
            for entry in result.entries:
                writer.writerow(
                    [
                        entry.label,
                        entry.uid,
                        entry.total_seconds,
                        round(entry.total_seconds / 3600.0, 2),
                        len(entry.days),
                        entry.first,
                        entry.last,
                        entry.exec_path or entry.proc_path,
                        "已迁移" if entry.uid in migrated else "未迁移",
                        _remark(entry, migrated),
                    ]
                )

    return _guard(path, run)


def write_daily_csv(path: Path, result: LoadResult) -> Path:
    def run() -> None:
        rows = []
        for entry in result.entries:
            for day in entry.days:
                rows.append((day.date, entry.label, entry.uid, day.seconds))
        rows.sort(key=lambda row: (row[0], row[1]))

        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["日期", "游戏名", "条目ID(uid)", "时长(秒)", "时长(小时)"])
            for date, label, uid, seconds in rows:
                writer.writerow([date, label, uid, seconds, round(seconds / 3600.0, 2)])

    return _guard(path, run)


def write_raw_json(
    path: Path,
    result: LoadResult,
    aliases: Optional[Mapping[str, str]] = None,
    migrated: Optional[Set[str]] = None,
    now: Optional[datetime.datetime] = None,
) -> Path:
    """完整原始转储。**时长单位是秒**，与 Etupirka 源数据一致。"""
    migrated = migrated or set()
    stamp = (now or datetime.datetime.now()).isoformat(timespec="seconds")

    def run() -> None:
        payload: Dict[str, Any] = {
            "exported_at": stamp,
            "source": str(result.path),
            "unit": "seconds",
            "entry_count": len(result.entries),
            "total_seconds": result.total_seconds,
            "identified_count": result.identified_count,
            "unidentified_count": result.unidentified_count,
            "entries": [
                {
                    "uid": entry.uid,
                    "label": entry.label,
                    "title": entry.title,
                    "title_source": entry.title_source,
                    "brand": entry.brand,
                    "saleday": entry.saleday,
                    "esid": entry.esid,
                    "exec_path": entry.exec_path,
                    "total_seconds": entry.total_seconds,
                    "first": entry.first,
                    "last": entry.last,
                    "migrated": entry.uid in migrated,
                    "flags": list(entry.flags),
                    "days": [
                        {"date": day.date, "seconds": day.seconds} for day in entry.days
                    ],
                }
                for entry in result.entries
            ],
            "aliases": dict(aliases or {}),
            "dropped": list(result.dropped),
            "warnings": list(result.warnings),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return _guard(path, run)


def write_report(
    path: Path,
    result: LoadResult,
    aliases: Optional[Mapping[str, str]] = None,
    migrated: Optional[Set[str]] = None,
    now: Optional[datetime.datetime] = None,
) -> Path:
    """给人读的报告：统计 + 提醒 + 丢弃 + 别名 + 两个清单。"""
    aliases = dict(aliases or {})
    migrated = migrated or set()
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    lines: List[str] = []
    add = lines.append

    add("Etupirka → Vnite 迁移助手 · 导出报告")
    add("=" * 52)
    add("导出时间 : %s" % stamp)
    add("数据源   : %s" % result.path)
    add("")
    add("== 统计 ==")
    add("条目数   : %d" % len(result.entries))
    add(
        "总时长   : %s（%d 秒）"
        % (format_duration(result.total_seconds), result.total_seconds)
    )
    add("已识别   : %d" % result.identified_count)
    add("未识别   : %d" % result.unidentified_count)
    add("已迁移   : %d / %d" % (len(migrated), len(result.entries)))
    add("")

    if result.warnings:
        add("== 提醒（%d 条）==" % len(result.warnings))
        for item in result.warnings:
            add("  - %s" % item)
        add("")

    if result.dropped:
        add("== 丢弃的记录（%d 条）==" % len(result.dropped))
        for item in result.dropped:
            add("  - %s" % item)
        add("")

    if aliases:
        add("== 别名表（%d 条）==" % len(aliases))
        titles = {entry.uid: entry.label for entry in result.entries}
        for uid in sorted(aliases):
            add("  %s  %s" % (uid, aliases[uid]))
            if uid not in titles:
                add("      （当前数据源里没有这个 uid）")
        add("")

    unidentified = [entry for entry in result.entries if not entry.identified]
    add("== 仍未识别（%d 条）==" % len(unidentified))
    if unidentified:
        for entry in unidentified:
            add(
                "  %-12s %6.2f 小时  %s ~ %s"
                % (entry.label, entry.total_seconds / 3600.0, entry.first, entry.last)
            )
        add("  提示：在界面里右键「重命名为…」即可给它们起名。")
    else:
        add("  无")
    add("")

    pending = [entry for entry in result.entries if entry.uid not in migrated]
    add("== 还未迁移到 Vnite（%d 条）==" % len(pending))
    if pending:
        for entry in pending:
            add("  %-40s %6.2f 小时" % (entry.label, entry.total_seconds / 3600.0))
    else:
        add("  无，全部条目都已复制过导入数据。")
    add("")

    add("== 生成的文件 ==")
    for name in GENERATED_FILES:
        add("  %s" % name)

    def run() -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return _guard(path, run)


def export_all(
    directory: Path,
    result: LoadResult,
    aliases: Optional[Mapping[str, str]] = None,
    migrated: Optional[Set[str]] = None,
    now: Optional[datetime.datetime] = None,
) -> List[Path]:
    """导出全部四个文件，返回写出的路径列表。"""
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(
            "无法创建导出目录：%s" % (exc.strerror or exc)
        ) from exc

    migrated = migrated or set()
    stamp = now or datetime.datetime.now()

    return [
        write_summary_csv(directory / SUMMARY_NAME, result, migrated),
        write_daily_csv(directory / DAILY_NAME, result),
        write_raw_json(directory / RAW_NAME, result, aliases, migrated, stamp),
        write_report(directory / REPORT_NAME, result, aliases, migrated, stamp),
    ]
