"""阶段 4 自测：命令行的表格渲染。"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from app import etupirka_db
from app.etupirka_db import load_entries
from app.model import LoadResult

from . import make_fixture
from .tmpdir import make_temp_dir


class WidthTests(unittest.TestCase):
    def test_ascii_counts_one_per_char(self) -> None:
        self.assertEqual(etupirka_db.display_width("abc"), 3)

    def test_cjk_counts_two_per_char(self) -> None:
        self.assertEqual(etupirka_db.display_width("中文"), 4)
        self.assertEqual(etupirka_db.display_width("テスト"), 6)

    def test_mixed(self) -> None:
        self.assertEqual(etupirka_db.display_width("a中b"), 4)

    def test_pad_left(self) -> None:
        self.assertEqual(etupirka_db._pad("中", 4), "中  ")

    def test_pad_right(self) -> None:
        self.assertEqual(etupirka_db._pad("中", 4, "right"), "  中")

    def test_pad_never_truncates(self) -> None:
        self.assertEqual(etupirka_db._pad("abcdef", 3), "abcdef")


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        make_fixture.build_standard(self.root / "user.db")
        self.result = load_entries(self.root)

    def render(self, func) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            func()
        return buffer.getvalue()

    def test_lists_every_entry(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(self.result))
        self.assertIn("数据源:", text)
        for entry in self.result.entries:
            self.assertIn(entry.label, text)

    def test_has_a_legend(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(self.result))
        self.assertIn("状态：· 正常   ! 有警告", text)

    def test_reports_totals(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(self.result))
        self.assertIn("条目: 7 条", text)
        self.assertIn("100720 秒", text)
        self.assertIn("已识别 6 条，未识别 1 条", text)

    def test_lists_dropped_rows_and_warnings(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(self.result))
        self.assertIn("丢弃的记录（3 条）", text)
        self.assertIn("提醒", text)

    def test_empty_result_does_not_crash(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(LoadResult(path=Path("x"))))
        self.assertIn("没有任何条目", text)

    def test_missing_day_is_shown_as_a_dash(self) -> None:
        from app.model import Entry

        result = LoadResult(path=Path("x"), entries=[Entry(uid="U", title="T")])
        text = self.render(lambda: etupirka_db._print_table(result))
        self.assertIn(" - ", text)
        self.assertIn("0.0 h", text)

    def test_separator_rule_matches_the_header_width(self) -> None:
        text = self.render(lambda: etupirka_db._print_table(self.result))
        lines = text.splitlines()
        header = next(
            index
            for index, line in enumerate(lines)
            if "游戏" in line and "时长" in line and "天数" in line
        )
        self.assertEqual(
            etupirka_db.display_width(lines[header]), len(lines[header + 1])
        )

    def test_main_prints_a_table_by_default(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = etupirka_db.main(["--db", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("未识别-01", buffer.getvalue())

    def test_main_json_flag_still_works(self) -> None:
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = etupirka_db.main(["--db", str(self.root), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["entry_count"], 7)


if __name__ == "__main__":
    unittest.main()
