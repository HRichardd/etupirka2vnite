"""阶段 0 自测：数据源的定位、校验与读取。

跑法（工程根目录下）::

    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from app import etupirka_db
from app.etupirka_db import EtupirkaDbError, load_entries, probe, resolve_db_path
from app.model import (
    FLAG_NO_PLAYTIME,
    FLAG_OVER_24H,
    FLAG_TOTAL_MISMATCH,
    FLAG_UNIDENTIFIED,
)

from . import make_fixture
from .tmpdir import make_temp_dir


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


# --------------------------------------------------------------------------
# resolve_db_path
# --------------------------------------------------------------------------


class ResolveDbPathTests(TempCase):
    def test_accepts_directory(self) -> None:
        db = make_fixture.build_standard(self.root / "user.db")
        self.assertEqual(resolve_db_path(self.root), db)

    def test_accepts_file(self) -> None:
        db = make_fixture.build_standard(self.root / "user.db")
        self.assertEqual(resolve_db_path(db), db)

    def test_strips_quotes_and_spaces(self) -> None:
        db = make_fixture.build_standard(self.root / "user.db")
        self.assertEqual(resolve_db_path('  "%s"  ' % db), db)

    def test_directory_without_user_db(self) -> None:
        with self.assertRaises(EtupirkaDbError) as ctx:
            resolve_db_path(self.root)
        self.assertEqual(str(ctx.exception), etupirka_db.ERR_NO_DB_IN_DIR)

    def test_missing_path(self) -> None:
        with self.assertRaises(EtupirkaDbError) as ctx:
            resolve_db_path(self.root / "nope")
        self.assertIn("找不到路径", str(ctx.exception))

    def test_empty_target(self) -> None:
        with self.assertRaises(EtupirkaDbError) as ctx:
            resolve_db_path("   ")
        self.assertEqual(str(ctx.exception), etupirka_db.ERR_EMPTY_TARGET)

    def test_unicode_directory(self) -> None:
        """路径里带中文/日文/空格时也要能找到（真实环境里到处都是）。"""
        folder = self.root / "Etupirka 目录 テスト"
        db = make_fixture.build_standard(folder / "user.db")
        self.assertEqual(resolve_db_path(folder), db)
        self.assertEqual(resolve_db_path(str(folder)), db)


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------


class ProbeTests(TempCase):
    def test_ok_for_directory(self) -> None:
        make_fixture.build_standard(self.root / "user.db")
        self.assertEqual(probe(self.root), "")

    def test_ok_for_file(self) -> None:
        db = make_fixture.build_standard(self.root / "user.db")
        self.assertEqual(probe(db), "")

    def test_ok_for_unicode_path(self) -> None:
        """file: URI 必须能正确解码非 ASCII 路径。"""
        folder = self.root / "游戏 ディレクトリ"
        make_fixture.build_standard(folder / "user.db")
        self.assertEqual(probe(folder), "")

    def test_reports_missing_user_db(self) -> None:
        self.assertIn("没有 user.db", probe(self.root))

    def test_reports_not_sqlite(self) -> None:
        bogus = self.root / "user.db"
        bogus.write_text("this is not a database", encoding="utf-8")
        self.assertEqual(probe(self.root), etupirka_db.ERR_NOT_SQLITE)

    def test_reports_missing_tables(self) -> None:
        make_fixture.create_db(self.root / "user.db", tables=("games", "playtime"))
        message = probe(self.root)
        self.assertIn("gametimeinfo", message)
        self.assertIn("gameexecinfo", message)

    def test_reports_missing_path(self) -> None:
        self.assertIn("找不到路径", probe(self.root / "nope"))


# --------------------------------------------------------------------------
# load_entries —— 标准 fixture
# --------------------------------------------------------------------------


class LoadStandardFixtureTests(TempCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = make_temp_dir()
        cls.root = Path(cls._tmp.name)
        make_fixture.build_standard(cls.root / "user.db")
        cls.result = load_entries(cls.root)
        cls.by_uid = {entry.uid: entry for entry in cls.result.entries}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_counts(self) -> None:
        self.assertEqual(len(self.result.entries), 7)
        self.assertEqual(self.result.identified_count, 6)
        self.assertEqual(self.result.unidentified_count, 1)

    def test_total_seconds(self) -> None:
        self.assertEqual(self.result.total_seconds, 100_720)

    def test_sorted_by_duration_desc(self) -> None:
        self.assertEqual(
            [entry.uid for entry in self.result.entries],
            [
                "HUGE000000000001",
                "ALPHA000000000001",
                "ORPHAN0000000001",
                "MISMATCH00000001",
                "BADDATE000000001",
                "NOPLAY0000000001",
                "ZEROTIME00000001",
            ],
        )

    def test_same_day_records_are_summed(self) -> None:
        alpha = self.by_uid["ALPHA000000000001"]
        self.assertEqual(
            [(day.date, day.seconds) for day in alpha.days],
            [("2024-01-01", 3600), ("2024-01-02", 4200)],
        )
        self.assertEqual(alpha.total_seconds, 7800)
        self.assertEqual((alpha.first, alpha.last), ("2024-01-01", "2024-01-02"))

    def test_clean_entry_has_no_flags(self) -> None:
        self.assertEqual(self.by_uid["ALPHA000000000001"].flags, [])
        self.assertEqual(self.by_uid["ALPHA000000000001"].exec_path, r"D:\games\alpha\alpha.exe")

    def test_orphan_is_labelled_unidentified(self) -> None:
        orphan = self.by_uid["ORPHAN0000000001"]
        self.assertTrue(orphan.has_flag(FLAG_UNIDENTIFIED))
        self.assertEqual(orphan.label, "未识别-01")
        self.assertEqual(orphan.title, "")
        self.assertEqual(orphan.total_seconds, 1800)

    def test_over_24h_is_flagged(self) -> None:
        huge = self.by_uid["HUGE000000000001"]
        self.assertTrue(huge.has_flag(FLAG_OVER_24H))
        self.assertEqual(huge.days[0].seconds, 90_000)

    def test_zero_and_negative_durations_become_no_playtime(self) -> None:
        zero = self.by_uid["ZEROTIME00000001"]
        self.assertTrue(zero.has_flag(FLAG_NO_PLAYTIME))
        self.assertEqual(zero.days, [])

    def test_game_without_any_record_is_listed(self) -> None:
        noplay = self.by_uid["NOPLAY0000000001"]
        self.assertTrue(noplay.has_flag(FLAG_NO_PLAYTIME))
        self.assertEqual(noplay.title, "Never Played")
        self.assertEqual(noplay.total_seconds, 0)

    def test_total_mismatch_beyond_tolerance(self) -> None:
        mismatch = self.by_uid["MISMATCH00000001"]
        self.assertTrue(mismatch.has_flag(FLAG_TOTAL_MISMATCH))

    def test_small_difference_is_tolerated(self) -> None:
        """容差 ±60 秒：ALPHA 的 gametimeinfo 与汇总完全相同，不该报警。"""
        self.assertFalse(self.by_uid["ALPHA000000000001"].has_flag(FLAG_TOTAL_MISMATCH))

    def test_invalid_rows_are_dropped_and_reported(self) -> None:
        self.assertEqual(len(self.result.dropped), 3)
        joined = "\n".join(self.result.dropped)
        self.assertIn("2024-13-45", joined)
        self.assertIn("不是正数", joined)
        self.assertTrue(
            any("共丢弃 3 条" in item for item in self.result.warnings),
            self.result.warnings,
        )

    def test_keeps_valid_row_of_a_partly_invalid_entry(self) -> None:
        bad = self.by_uid["BADDATE000000001"]
        self.assertEqual([(day.date, day.seconds) for day in bad.days], [("2024-02-02", 120)])


class ToleranceBoundaryTests(TempCase):
    def test_difference_of_exactly_60_seconds_is_accepted(self) -> None:
        make_fixture.create_db(
            self.root / "user.db",
            games=[("BOUNDARY00000001", "Boundary", None, None, 0)],
            playtime=[("2024-01-01", "BOUNDARY00000001", 1000)],
            gametimeinfo=[("BOUNDARY00000001", 1060, "", "")],
        )
        entry = load_entries(self.root).entries[0]
        self.assertFalse(entry.has_flag(FLAG_TOTAL_MISMATCH))

    def test_difference_of_61_seconds_is_reported(self) -> None:
        make_fixture.create_db(
            self.root / "user.db",
            games=[("BOUNDARY00000001", "Boundary", None, None, 0)],
            playtime=[("2024-01-01", "BOUNDARY00000001", 1000)],
            gametimeinfo=[("BOUNDARY00000001", 1061, "", "")],
        )
        entry = load_entries(self.root).entries[0]
        self.assertTrue(entry.has_flag(FLAG_TOTAL_MISMATCH))


# --------------------------------------------------------------------------
# 其他读取场景
# --------------------------------------------------------------------------


class AliasTests(TempCase):
    """别名表接入读取层：显式重命名优先于源数据。"""

    def setUp(self) -> None:
        super().setUp()
        make_fixture.build_standard(self.root / "user.db")

    def _entry(self, result, uid: str):
        return next(entry for entry in result.entries if entry.uid == uid)

    def test_alias_fills_in_a_missing_title(self) -> None:
        result = load_entries(self.root, aliases={"ORPHAN0000000001": "真名"})
        orphan = self._entry(result, "ORPHAN0000000001")
        self.assertEqual(orphan.title, "真名")
        self.assertEqual(orphan.label, "真名")
        self.assertEqual(orphan.title_source, "alias")
        self.assertFalse(orphan.has_flag(FLAG_UNIDENTIFIED))
        self.assertEqual(result.unidentified_count, 0)

    def test_alias_overrides_an_existing_title(self) -> None:
        result = load_entries(self.root, aliases={"ALPHA000000000001": "改过的名字"})
        alpha = self._entry(result, "ALPHA000000000001")
        self.assertEqual(alpha.title, "改过的名字")
        self.assertEqual(alpha.title_source, "alias")

    def test_other_entries_keep_their_source(self) -> None:
        result = load_entries(self.root, aliases={"ORPHAN0000000001": "真名"})
        self.assertEqual(
            self._entry(result, "ALPHA000000000001").title_source, "user.db"
        )

    def test_unknown_alias_uid_is_ignored(self) -> None:
        result = load_entries(self.root, aliases={"GHOST": "X"})
        self.assertEqual(len(result.entries), 7)
        self.assertEqual(result.unidentified_count, 1)

    def test_blank_alias_is_ignored(self) -> None:
        result = load_entries(self.root, aliases={"ORPHAN0000000001": "   "})
        self.assertTrue(
            self._entry(result, "ORPHAN0000000001").has_flag(FLAG_UNIDENTIFIED)
        )

    def test_without_aliases_behaviour_is_unchanged(self) -> None:
        result = load_entries(self.root)
        self.assertEqual(result.unidentified_count, 1)
        self.assertEqual(self._entry(result, "ORPHAN0000000001").label, "未识别-01")

    def test_alias_does_not_affect_play_time(self) -> None:
        plain = load_entries(self.root)
        aliased = load_entries(self.root, aliases={"ORPHAN0000000001": "真名"})
        self.assertEqual(plain.total_seconds, aliased.total_seconds)


class LoadEdgeCaseTests(TempCase):
    def test_empty_database(self) -> None:
        make_fixture.create_db(self.root / "user.db")
        result = load_entries(self.root)
        self.assertEqual(result.entries, [])
        self.assertEqual(result.total_seconds, 0)
        self.assertIn("数据库里没有游玩记录。", result.warnings)

    def test_impossible_but_well_formatted_date_is_dropped(self) -> None:
        """格式对但日子不存在（Vnite 的 parseLocalDate 同样会拒绝）。"""
        make_fixture.create_db(
            self.root / "user.db",
            games=[("FAKEDATE00000001", "Fake", None, None, 0)],
            playtime=[
                ("2024-02-30", "FAKEDATE00000001", 100),  # 2 月没有 30 号
                ("2023-02-29", "FAKEDATE00000001", 100),  # 2023 不是闰年
                ("2024-02-29", "FAKEDATE00000001", 100),  # 2024 是闰年，应保留
            ],
        )
        result = load_entries(self.root)
        self.assertEqual(
            [(day.date, day.seconds) for day in result.entries[0].days],
            [("2024-02-29", 100)],
        )
        self.assertEqual(len(result.dropped), 2)
        self.assertIn("不是一个真实存在的日子", "\n".join(result.dropped))

    def test_missing_table_raises(self) -> None:
        make_fixture.create_db(self.root / "user.db", tables=("games", "playtime"))
        with self.assertRaises(EtupirkaDbError) as ctx:
            load_entries(self.root)
        self.assertIn("缺少", str(ctx.exception))

    def test_not_sqlite_raises(self) -> None:
        (self.root / "user.db").write_text("nope", encoding="utf-8")
        with self.assertRaises(EtupirkaDbError) as ctx:
            load_entries(self.root)
        self.assertEqual(str(ctx.exception), etupirka_db.ERR_NOT_SQLITE)

    def test_plays_without_games_table_row_still_load(self) -> None:
        """所有条目都是孤儿时，全部应被编号而不错乱。"""
        make_fixture.create_db(
            self.root / "user.db",
            playtime=[
                ("2024-01-01", "ORPHANAAAAAAAAAA", 600),
                ("2024-01-02", "ORPHANBBBBBBBBBB", 300),
            ],
        )
        result = load_entries(self.root)
        self.assertEqual([entry.label for entry in result.entries], ["未识别-01", "未识别-02"])
        self.assertEqual(result.unidentified_count, 2)

    def test_non_ascii_title_survives(self) -> None:
        title = "とける風花とシロうさぎ"
        make_fixture.create_db(
            self.root / "user.db",
            games=[("UTF8000000000001", title, None, None, 0)],
            playtime=[("2026-08-23", "UTF8000000000001", 12705)],
        )
        entry = load_entries(self.root).entries[0]
        self.assertEqual(entry.title, title)
        self.assertEqual(entry.label, title)


class ReadOnlySafetyTests(TempCase):
    """这工具唯一的职责就是只读地搬数据，必须证明它没碰过原始库。"""

    def test_source_database_is_untouched(self) -> None:
        db = make_fixture.build_standard(self.root / "user.db")
        before_hash = sha256(db)
        before_mtime = db.stat().st_mtime_ns
        before_files = sorted(item.name for item in self.root.iterdir())

        load_entries(self.root)

        self.assertEqual(sha256(db), before_hash)
        self.assertEqual(db.stat().st_mtime_ns, before_mtime)
        self.assertEqual(sorted(item.name for item in self.root.iterdir()), before_files)

    def test_no_journal_or_wal_left_behind(self) -> None:
        make_fixture.build_standard(self.root / "user.db")
        load_entries(self.root)
        leftovers = [
            item.name
            for item in self.root.iterdir()
            if item.name.endswith(("-journal", "-wal", "-shm"))
        ]
        self.assertEqual(leftovers, [])


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------


class CommandLineTests(TempCase):
    def test_json_output(self) -> None:
        import contextlib
        import io
        import json

        make_fixture.build_standard(self.root / "user.db")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = etupirka_db.main(["--db", str(self.root), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["entry_count"], 7)
        self.assertEqual(payload["total_seconds"], 100_720)
        self.assertEqual(payload["entries"][2]["label"], "未识别-01")

    def test_bad_path_returns_2_and_prints_reason(self) -> None:
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = etupirka_db.main(["--db", str(self.root / "nope")])

        self.assertEqual(code, 2)
        self.assertIn("错误：", err.getvalue())


if __name__ == "__main__":
    unittest.main()
