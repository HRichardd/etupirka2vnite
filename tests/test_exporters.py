"""阶段 3 自测：导出。"""

from __future__ import annotations

import csv
import datetime
import json
import unittest
from pathlib import Path

from app import exporters
from app.etupirka_db import load_entries
from app.model import FLAG_UNIDENTIFIED

from . import make_fixture
from .tmpdir import make_temp_dir


class ExportCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"

        make_fixture.build_standard(self.root / "user.db")
        self.result = load_entries(self.root)
        self.now = datetime.datetime(2026, 8, 25, 12, 0, 0)

    def export(self, **kwargs):
        return exporters.export_all(self.out, self.result, now=self.now, **kwargs)

    def read_csv(self, name: str):
        with open(self.out / name, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


class ExportAllTests(ExportCase):
    def test_creates_exactly_the_four_files(self) -> None:
        written = self.export()
        self.assertEqual(len(written), 4)
        self.assertEqual({path.name for path in written}, set(exporters.GENERATED_FILES))
        for path in written:
            self.assertTrue(path.is_file(), path)

    def test_creates_a_missing_directory(self) -> None:
        self.assertFalse(self.out.exists())
        self.export()
        self.assertTrue(self.out.is_dir())

    def test_does_not_delete_foreign_files(self) -> None:
        self.out.mkdir(parents=True)
        keep = self.out / "我的笔记.txt"
        keep.write_text("别删我", encoding="utf-8")

        self.export()

        self.assertTrue(keep.is_file())
        self.assertEqual(keep.read_text(encoding="utf-8"), "别删我")

    def test_is_repeatable_without_piling_up_files(self) -> None:
        self.export()
        self.export()
        self.assertEqual(len(list(self.out.iterdir())), 4)

    def test_reports_an_unwritable_target(self) -> None:
        blocker = self.root / "blocker"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(exporters.ExportError):
            exporters.export_all(blocker / "sub", self.result)

    def test_csv_files_have_a_bom_for_excel(self) -> None:
        self.export()
        for name in (exporters.SUMMARY_NAME, exporters.DAILY_NAME):
            raw = (self.out / name).read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), name)


class SummaryCsvTests(ExportCase):
    def test_one_row_per_entry(self) -> None:
        self.export()
        rows = self.read_csv(exporters.SUMMARY_NAME)
        self.assertEqual(len(rows), 7)

    def test_values(self) -> None:
        self.export()
        rows = self.read_csv(exporters.SUMMARY_NAME)
        alpha = next(row for row in rows if row["游戏名"] == "Alpha Game")
        self.assertEqual(alpha["总时长(秒)"], "7800")
        self.assertEqual(alpha["总时长(小时)"], "2.17")
        self.assertEqual(alpha["有记录天数"], "2")
        self.assertEqual(alpha["首次游玩"], "2024-01-01")
        self.assertEqual(alpha["最后游玩"], "2024-01-02")
        self.assertEqual(alpha["状态"], "未迁移")

    def test_marks_migrated_entries(self) -> None:
        entry = self.result.entries[0]
        self.export(migrated={entry.uid})
        rows = self.read_csv(exporters.SUMMARY_NAME)
        row = next(item for item in rows if item["条目ID(uid)"] == entry.uid)
        self.assertEqual(row["状态"], "已迁移")
        self.assertIn("已迁移", row["备注"])

    def test_notes_flags(self) -> None:
        self.export()
        rows = self.read_csv(exporters.SUMMARY_NAME)
        orphan = next(row for row in rows if row["条目ID(uid)"] == "ORPHAN0000000001")
        self.assertIn("未识别", orphan["备注"])


class DailyCsvTests(ExportCase):
    def test_one_row_per_day_sorted_by_date(self) -> None:
        self.export()
        rows = self.read_csv(exporters.DAILY_NAME)
        self.assertEqual(
            len(rows), sum(len(entry.days) for entry in self.result.entries)
        )
        dates = [row["日期"] for row in rows]
        self.assertEqual(dates, sorted(dates))

    def test_seconds_are_preserved(self) -> None:
        self.export()
        rows = self.read_csv(exporters.DAILY_NAME)
        row = next(
            item
            for item in rows
            if item["游戏名"] == "Alpha Game" and item["日期"] == "2024-01-02"
        )
        self.assertEqual(row["时长(秒)"], "4200")  # 3600 + 600 已合并


class RawJsonTests(ExportCase):
    def test_shape(self) -> None:
        self.export(aliases={"UID": "Name"})
        payload = json.loads((self.out / exporters.RAW_NAME).read_text(encoding="utf-8"))
        self.assertEqual(payload["entry_count"], 7)
        self.assertEqual(payload["total_seconds"], 100720)
        self.assertEqual(payload["unit"], "seconds")
        self.assertEqual(payload["aliases"], {"UID": "Name"})
        self.assertEqual(payload["exported_at"], "2026-08-25T12:00:00")
        self.assertTrue(all("days" in entry for entry in payload["entries"]))

    def test_records_dropped_and_warnings(self) -> None:
        self.export()
        payload = json.loads((self.out / exporters.RAW_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["dropped"]), 3)
        self.assertTrue(payload["warnings"])


class ReportTests(ExportCase):
    def text(self) -> str:
        return (self.out / exporters.REPORT_NAME).read_text(encoding="utf-8")

    def test_contains_the_key_facts(self) -> None:
        self.export()
        text = self.text()
        self.assertIn("导出报告", text)
        self.assertIn(str(self.root / "user.db"), text)
        self.assertIn("2026-08-25 12:00:00", text)
        self.assertIn("总时长", text)
        self.assertIn("仍未识别", text)
        self.assertIn("未识别-01", text)
        self.assertIn("丢弃的记录", text)

    def test_lists_aliases(self) -> None:
        orphan = next(
            entry for entry in self.result.entries if entry.has_flag(FLAG_UNIDENTIFIED)
        )
        self.export(aliases={orphan.uid: "真名"})
        text = self.text()
        self.assertIn("别名表", text)
        self.assertIn("真名", text)

    def test_flags_alias_for_a_uid_not_in_this_source(self) -> None:
        self.export(aliases={"GHOSTUID": "Ghost"})
        self.assertIn("当前数据源里没有这个 uid", self.text())

    def test_says_all_done_when_everything_migrated(self) -> None:
        self.export(migrated={entry.uid for entry in self.result.entries})
        self.assertIn("全部条目都已复制过导入数据", self.text())

    def test_lists_pending_entries(self) -> None:
        self.export(migrated={self.result.entries[0].uid})
        text = self.text()
        self.assertIn("还未迁移到 Vnite", text)
        self.assertIn("Alpha Game", text)


if __name__ == "__main__":
    unittest.main()
