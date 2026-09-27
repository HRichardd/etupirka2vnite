"""只读读取 Etupirka 的 ``user.db``。

对界面层暴露三个函数::

    resolve_db_path(target)  -> Path        目录或文件 → user.db 路径
    probe(target)            -> str         "" 表示校验通过，否则是给用户看的中文原因
    load_entries(target)     -> LoadResult

命令行自测::

    python -m app.etupirka_db --db "D:\\gal\\Etupirka-0.6.0"
    python -m app.etupirka_db --db <路径> --json

全程只读：用 ``file:...?mode=ro`` 打开，不写、不建 journal、不碰原文件。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence

from .model import (
    FLAG_NO_PLAYTIME,
    FLAG_OVER_24H,
    FLAG_TOTAL_MISMATCH,
    MAX_DAY_SECONDS,
    Day,
    Entry,
    LoadResult,
    format_duration,
    label_entries,
)
from .paths import DB_FILENAME

REQUIRED_TABLES = ("games", "gametimeinfo", "playtime", "gameexecinfo")

SQLITE_MAGIC = b"SQLite format 3\x00"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 每日记录之和与 gametimeinfo.playtime 的允许误差。
#: 实测 Etupirka 自己也会差个几十秒（两者在不同时机落盘），所以不能要求相等。
TOTAL_TOLERANCE_SECONDS = 60

ERR_EMPTY_TARGET = "没有指定路径。"
ERR_NOT_FOUND = "找不到路径：{path}"
ERR_NO_DB_IN_DIR = "这个目录里没有 user.db，请选择 Etupirka 所在的文件夹。"
ERR_NOT_FILE = "路径不是一个文件：{path}"
ERR_NOT_SQLITE = "user.db 不是有效的 SQLite 数据库，可能已损坏。"
ERR_BUSY = "无法打开 user.db，可能正被 Etupirka 占用。请先关闭 Etupirka 再试。"
ERR_UNREADABLE = "无法读取 user.db：{reason}"
ERR_MISSING_TABLES = "缺少 {tables} 表，这不是 Etupirka 的数据目录，或数据库版本不受支持。"


class EtupirkaDbError(Exception):
    """带中文提示的读取错误。``str(exc)`` 可直接展示给用户。"""


# --------------------------------------------------------------------------
# 定位与校验
# --------------------------------------------------------------------------


def resolve_db_path(target: str | Path) -> Path:
    """把「用户选的东西」解析成 user.db 的路径。

    接受三种输入：Etupirka 目录、user.db 文件本身、user.db 的完整路径。
    """
    raw = str(target).strip().strip('"')
    if not raw:
        raise EtupirkaDbError(ERR_EMPTY_TARGET)

    path = Path(raw).expanduser()

    if path.is_dir():
        candidate = path / DB_FILENAME
        if not candidate.is_file():
            raise EtupirkaDbError(ERR_NO_DB_IN_DIR)
        return candidate

    if path.is_file():
        return path

    if path.exists():
        raise EtupirkaDbError(ERR_NOT_FILE.format(path=path))

    raise EtupirkaDbError(ERR_NOT_FOUND.format(path=path))


def _check_sqlite_header(path: Path) -> None:
    try:
        with open(path, "rb") as handle:
            head = handle.read(len(SQLITE_MAGIC))
    except OSError as exc:
        raise EtupirkaDbError(ERR_UNREADABLE.format(reason=exc.strerror or exc)) from exc

    if head != SQLITE_MAGIC:
        raise EtupirkaDbError(ERR_NOT_SQLITE)


def _connect_ro(path: Path) -> sqlite3.Connection:
    """以只读模式打开。

    用 ``as_uri()`` 生成 file: URI，这样路径里的中文、日文、空格、``#`` 都能被
    SQLite 正确解码（手工拼 ``file:`` 前缀会在这些字符上翻车）。
    """
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _existing_tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("select name from sqlite_master where type = 'table'")
    return {row[0] for row in rows}


def _missing_tables(con: sqlite3.Connection) -> List[str]:
    present = _existing_tables(con)
    return [name for name in REQUIRED_TABLES if name not in present]


def probe(target: str | Path) -> str:
    """完整校验一个数据源。

    返回 ``""`` 表示可以用；否则返回一句可以直接显示给用户的中文原因。
    界面在用户每次选完路径后调用它，保证不会进入「加载了一半」的状态。
    """
    try:
        path = resolve_db_path(target)
        _check_sqlite_header(path)
    except EtupirkaDbError as exc:
        return str(exc)

    try:
        con = _connect_ro(path)
    except sqlite3.Error:
        return ERR_BUSY

    try:
        missing = _missing_tables(con)
    except sqlite3.DatabaseError:
        return ERR_NOT_SQLITE
    except sqlite3.Error:
        return ERR_BUSY
    finally:
        con.close()

    if missing:
        return ERR_MISSING_TABLES.format(tables="、".join(missing))
    return ""


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------


def load_entries(
    target: str | Path, aliases: Mapping[str, str] | None = None
) -> LoadResult:
    """读取全部条目。

    ``aliases`` 是 ``uid → 名字`` 的别名表，用于给未识别条目（以及需要修正的
    已识别条目）指定显示名。显式别名优先于 ``games.title``。

    抛出 :class:`EtupirkaDbError` 表示数据源不可用；
    返回结果里的 ``warnings`` / ``dropped`` 则是「能读，但有情况需要你知道」。
    """
    path = resolve_db_path(target)
    _check_sqlite_header(path)

    try:
        con = _connect_ro(path)
    except sqlite3.Error as exc:
        raise EtupirkaDbError(ERR_BUSY) from exc

    try:
        con.row_factory = sqlite3.Row
        missing = _missing_tables(con)
        if missing:
            raise EtupirkaDbError(ERR_MISSING_TABLES.format(tables="、".join(missing)))

        games = {
            row["uid"]: row
            for row in con.execute("select uid, title, brand, saleday, esid from games")
        }
        execs = {
            row["uid"]: row
            for row in con.execute("select uid, procpath, execpath from gameexecinfo")
        }
        totals = {
            row["uid"]: row
            for row in con.execute(
                "select uid, playtime, firstplay, lastplay from gametimeinfo"
            )
        }
        raw_rows = list(con.execute("select datetime, game, playtime from playtime"))
    except sqlite3.DatabaseError as exc:
        raise EtupirkaDbError(ERR_NOT_SQLITE) from exc
    except sqlite3.Error as exc:
        raise EtupirkaDbError(ERR_BUSY) from exc
    finally:
        con.close()

    return _build_result(path, games, execs, totals, raw_rows, aliases)


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _field(row: Any, name: str, default: Any = None) -> Any:
    """从一行里安全取名。

    ``sqlite3.Row`` 没有 ``.get()``，查不到的行又是 ``None``，
    这里统一兜住，调用处就不用到处写 ``or {}`` 了。
    """
    if row is None:
        return default
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _day_problem(date: str) -> str:
    """``""`` 表示日期可用，否则返回不能用的原因。

    只查格式不够：``2024-13-45`` 能过正则，但 Vnite 的 ``parseLocalDate``
    会拒绝它，粘进导入框必然失败，所以必须按真实日历校验。
    """
    if not DATE_RE.match(date):
        return "日期不是 YYYY-MM-DD 格式"
    try:
        datetime.date(int(date[0:4]), int(date[5:7]), int(date[8:10]))
    except ValueError:
        return "日期不是一个真实存在的日子"
    return ""


def _build_result(
    path: Path,
    games: Mapping[str, Any],
    execs: Mapping[str, Any],
    totals: Mapping[str, Any],
    raw_rows: Iterable[Any],
    aliases: Mapping[str, str] | None = None,
) -> LoadResult:
    # 1) 归集每日记录，顺手剔掉无效行
    grouped: dict[str, dict[str, int]] = defaultdict(dict)
    dropped: List[str] = []

    for row in raw_rows:
        uid = str(row["game"] or "").strip()
        date = str(row["datetime"] or "").strip()
        seconds = row["playtime"]

        if not uid:
            dropped.append("丢弃 1 条记录：game 字段为空")
            continue
        problem = _day_problem(date)
        if problem:
            dropped.append("丢弃 %s / %s：%s" % (uid, date, problem))
            continue
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            dropped.append("丢弃 %s / %s：时长不是整数（%r）" % (uid, date, seconds))
            continue
        if seconds <= 0:
            dropped.append("丢弃 %s / %s：时长不是正数（%d 秒）" % (uid, date, seconds))
            continue

        bucket = grouped[uid]
        # 同日多条求和：与 Vnite 的 normalizeDailyPlayTimes 规则一致
        bucket[date] = bucket.get(date, 0) + seconds

    # 2) 组装条目。games 里有、但从未玩过的条目也要列出来
    all_uids = sorted(set(grouped) | set(games))
    entries: List[Entry] = []

    for uid in all_uids:
        game = games.get(uid)
        info = execs.get(uid)
        total_row = totals.get(uid)
        days = sorted(grouped.get(uid, {}).items())

        original_title = str(_field(game, "title", "")).strip()
        alias = str((aliases or {}).get(uid) or "").strip()
        if alias:
            # 用户的显式重命名优先于源数据：原标题可能是被截断的
            title, title_source = alias, "alias"
        elif original_title:
            title, title_source = original_title, "user.db"
        else:
            title, title_source = "", ""

        entry = Entry(
            uid=uid,
            title=title,
            brand=str(_field(game, "brand", "")).strip(),
            saleday=str(_field(game, "saleday", "")),
            esid=_to_int(_field(game, "esid"), -1),
            exec_path=str(_field(info, "execpath", "")),
            proc_path=str(_field(info, "procpath", "")),
            firstplay=str(_field(total_row, "firstplay", "")),
            lastplay=str(_field(total_row, "lastplay", "")),
            days=[Day(date=date, seconds=seconds) for date, seconds in days],
        )
        entry.title_source = title_source
        if not days:
            entry.flags.append(FLAG_NO_PLAYTIME)
        entries.append(entry)

    # 3) 排序后再编号：时长降序，同长度按名字稳定排列
    entries.sort(key=lambda item: (-item.total_seconds, item.title or item.uid))
    label_entries(entries)

    # 4) 生成给人看的提醒
    warnings: List[str] = []
    for entry in entries:
        if entry.has_flag(FLAG_NO_PLAYTIME):
            warnings.append(
                "「%s」在 games 表里有条目，但没有任何游玩记录。" % entry.label
            )
        if any(day.seconds > MAX_DAY_SECONDS for day in entry.days):
            entry.flags.append(FLAG_OVER_24H)
            warnings.append(
                "「%s」有单日超过 24 小时的记录，Vnite 计算时会封顶到 24h。" % entry.label
            )

        expected_row = totals.get(entry.uid)
        if expected_row is not None and entry.days:
            recorded = _to_int(_field(expected_row, "playtime"), 0)
            actual = entry.total_seconds
            if abs(recorded - actual) > TOTAL_TOLERANCE_SECONDS:
                entry.flags.append(FLAG_TOTAL_MISMATCH)
                warnings.append(
                    "「%s」每日记录合计 %d 秒，与 gametimeinfo 记录的 %d 秒相差 %d 秒。"
                    % (entry.label, actual, recorded, abs(recorded - actual))
                )

    if not entries:
        warnings.append("数据库里没有游玩记录。")
    if dropped:
        warnings.append("共丢弃 %d 条无效记录。" % len(dropped))

    return LoadResult(path=path, entries=entries, dropped=dropped, warnings=warnings)


# --------------------------------------------------------------------------
# 命令行（阶段 0 的自测入口）
# --------------------------------------------------------------------------


def display_width(text: str) -> int:
    """终端里的显示宽度。中日文占 2 列，否则对不齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _print_table(result: LoadResult) -> None:
    print("数据源: %s" % result.path)
    print(
        "条目: %d 条，合计 %s（%d 秒）"
        % (len(result.entries), format_duration(result.total_seconds), result.total_seconds)
    )
    print(
        "已识别 %d 条，未识别 %d 条"
        % (result.identified_count, result.unidentified_count)
    )
    print()

    if not result.entries:
        print("（没有任何条目）")
    else:
        columns = [
            ("#", 3, "right"),
            ("状态", 4, "left"),
            ("游戏", 38, "left"),
            ("时长", 9, "right"),
            ("天数", 4, "right"),
            ("首次游玩", 11, "left"),
            ("最后游玩", 11, "left"),
        ]
        header = "  ".join(
            _pad(name, width, align) for name, width, align in columns
        ).rstrip()
        print(header)
        print("-" * display_width(header))

        for index, entry in enumerate(result.entries, 1):
            mark = "!" if entry.flags else "·"
            hours = "%.1f h" % (entry.total_seconds / 3600.0)
            row = [
                _pad(str(index), 3, "right"),
                _pad(mark, 4, "left"),
                _pad(entry.label, 38, "left"),
                _pad(hours, 9, "right"),
                _pad(str(len(entry.days)), 4, "right"),
                _pad(entry.first or "-", 11, "left"),
                _pad(entry.last or "-", 11, "left"),
            ]
            print("  ".join(row).rstrip())

        print()
        print("状态：· 正常   ! 有警告")

    if result.dropped:
        print()
        print("丢弃的记录（%d 条）：" % len(result.dropped))
        for item in result.dropped:
            print("  - %s" % item)

    if result.warnings:
        print()
        print("提醒（%d 条）：" % len(result.warnings))
        for item in result.warnings:
            print("  - %s" % item)


def _to_json(result: LoadResult) -> dict:
    return {
        "path": str(result.path),
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
                "esid": entry.esid,
                "exec_path": entry.exec_path,
                "total_seconds": entry.total_seconds,
                "first": entry.first,
                "last": entry.last,
                "day_count": len(entry.days),
                "days": [{"date": day.date, "seconds": day.seconds} for day in entry.days],
                "flags": entry.flags,
            }
            for entry in result.entries
        ],
        "dropped": result.dropped,
        "warnings": result.warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.etupirka_db",
        description="读取 Etupirka 的 user.db 并打印条目清单（阶段 0 自测入口）。",
    )
    parser.add_argument("--db", required=True, help="Etupirka 目录，或 user.db 的路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于脚本核对")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    try:
        result = load_entries(args.db)
    except EtupirkaDbError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2

    if args.json:
        json.dump(_to_json(result), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_table(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
