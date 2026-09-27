"""生成合成的 ``user.db``，供单元测试使用。

表结构与真实 Etupirka 一致，只有一处例外：``playtime`` **故意不设主键**。
真实库里 ``PRIMARY KEY(datetime, game)`` 让同日重复不可能出现，但读取层仍然
按「同日求和」做防御性合并，所以要能造出重复行来验证那条路径。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA = {
    "games": (
        "CREATE TABLE `games` ("
        "`uid` TEXT NOT NULL, `title` TEXT, `brand` TEXT, `saleday` TEXT, "
        "`esid` INTEGER DEFAULT 0, PRIMARY KEY(uid))"
    ),
    "gametimeinfo": (
        "CREATE TABLE `gametimeinfo` ("
        "`uid` TEXT, `playtime` INTEGER DEFAULT 0, `firstplay` TEXT, `lastplay` TEXT, "
        "PRIMARY KEY(uid))"
    ),
    # 注意：这里刻意没有 PRIMARY KEY(datetime, game)
    "playtime": (
        "CREATE TABLE `playtime` ("
        "`datetime` TEXT NOT NULL, `game` TEXT NOT NULL, "
        "`playtime` INTEGER NOT NULL DEFAULT 0)"
    ),
    "gameexecinfo": (
        "CREATE TABLE `gameexecinfo` ("
        "`uid` TEXT, `proc_neq_exec` INTEGER NOT NULL DEFAULT 0, "
        "`procpath` TEXT, `execpath` TEXT, PRIMARY KEY(uid))"
    ),
}

DEFAULT_TABLES: tuple[str, ...] = tuple(SCHEMA)


def create_db(
    path: str | Path,
    *,
    games: Iterable[Sequence[object]] = (),
    playtime: Iterable[Sequence[object]] = (),
    gametimeinfo: Iterable[Sequence[object]] = (),
    gameexecinfo: Iterable[Sequence[object]] = (),
    tables: Sequence[str] = DEFAULT_TABLES,
) -> Path:
    """按真实表结构建一个库。

    ``gameexecinfo`` 的行按 ``(uid, procpath, execpath)`` 给，
    ``proc_neq_exec`` 固定写 0。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    con = sqlite3.connect(str(path))
    try:
        created = set(tables)
        for name in tables:
            con.execute(SCHEMA[name])

        # 只往真正建出来的表里插数据，否则「故意缺表」的 fixture 会自己先炸
        inserts = (
            (
                "games",
                "insert into games (uid, title, brand, saleday, esid) values (?,?,?,?,?)",
                games,
            ),
            (
                "playtime",
                "insert into playtime (datetime, game, playtime) values (?,?,?)",
                playtime,
            ),
            (
                "gametimeinfo",
                "insert into gametimeinfo (uid, playtime, firstplay, lastplay) "
                "values (?,?,?,?)",
                gametimeinfo,
            ),
            (
                "gameexecinfo",
                "insert into gameexecinfo (uid, proc_neq_exec, procpath, execpath) "
                "values (?,0,?,?)",
                gameexecinfo,
            ),
        )
        for name, sql, rows in inserts:
            if name in created:
                con.executemany(sql, [tuple(row) for row in rows])
        con.commit()
    finally:
        con.close()

    return path


def build_standard(path: str | Path) -> Path:
    """标准 fixture，一处覆盖一种边界情况。

    ====================  ==========================================
    uid                   覆盖点
    ====================  ==========================================
    ALPHA000000000001     正常条目；2024-01-02 有两条 → 应合并为 7800 秒
    ORPHAN0000000001      孤儿：playtime 里有、games 里没有
    HUGE000000000001      单日 25 小时 → 应打 over_24h 标记
    BADDATE000000001      一条非法日期（丢弃）+ 一条合法（保留）
    ZEROTIME00000001      0 秒与负秒（都丢弃）→ 变成无记录条目
    NOPLAY0000000001      games 里有、但一条 playtime 都没有
    MISMATCH00000001      汇总 1000 秒 vs gametimeinfo 2000 秒 → 超出容差
    ====================  ==========================================
    """
    return create_db(
        path,
        games=[
            ("ALPHA000000000001", "Alpha Game", "BrandA", "2024-01-01", 101),
            ("HUGE000000000001", "Huge Day", "BrandB", "2024-03-01", 102),
            ("BADDATE000000001", "Bad Date", None, None, 0),
            ("ZEROTIME00000001", "Zero Time", None, None, 0),
            ("NOPLAY0000000001", "Never Played", "BrandC", "2020-01-01", 103),
            ("MISMATCH00000001", "Mismatch", None, None, 0),
        ],
        playtime=[
            ("2024-01-01", "ALPHA000000000001", 3600),
            ("2024-01-02", "ALPHA000000000001", 3600),
            ("2024-01-02", "ALPHA000000000001", 600),  # 同日重复 → 合并
            ("2023-05-05", "ORPHAN0000000001", 1800),  # 孤儿
            ("2024-03-03", "HUGE000000000001", 90000),  # 25 小时
            ("2024-13-45", "BADDATE000000001", 100),  # 非法日期
            ("2024-02-02", "BADDATE000000001", 120),  # 合法
            ("2024-04-04", "ZEROTIME00000001", 0),  # 非正
            ("2024-04-05", "ZEROTIME00000001", -5),  # 非正
            ("2024-06-01", "MISMATCH00000001", 1000),
        ],
        gametimeinfo=[
            ("ALPHA000000000001", 7800, "2024-01-01 10:00:00", "2024-01-02 12:00:00"),
            ("HUGE000000000001", 90000, "2024-03-03 00:00:00", "2024-03-04 01:00:00"),
            ("MISMATCH00000001", 2000, "2024-06-01 09:00:00", "2024-06-01 12:00:00"),
        ],
        gameexecinfo=[
            (
                "ALPHA000000000001",
                r"D:\games\alpha\alpha.exe",
                r"D:\games\alpha\alpha.exe",
            ),
        ],
    )
