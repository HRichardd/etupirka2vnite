"""阶段 4 自测：中间模型的纯逻辑。"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.model import (
    FLAG_LABELS,
    FLAG_NO_PLAYTIME,
    FLAG_OVER_24H,
    FLAG_TOTAL_MISMATCH,
    FLAG_UNIDENTIFIED,
    UNIDENTIFIED_LABEL,
    Day,
    Entry,
    LoadResult,
    format_duration,
    label_entries,
)


def make_entry(uid: str = "UID", title: str = "", days=(), **kwargs) -> Entry:
    entry = Entry(
        uid=uid, title=title, days=[Day(date, seconds) for date, seconds in days], **kwargs
    )
    entry.title_source = "user.db" if title else ""
    return entry


class EntryTests(unittest.TestCase):
    def test_total_seconds_sums_the_days(self) -> None:
        entry = make_entry(days=[("2024-01-01", 60), ("2024-01-02", 90)])
        self.assertEqual(entry.total_seconds, 150)

    def test_first_and_last_come_from_the_first_and_last_day(self) -> None:
        entry = make_entry(
            days=[("2024-01-01", 60), ("2024-03-01", 60), ("2024-02-01", 60)]
        )
        self.assertEqual(entry.first, "2024-01-01")
        self.assertEqual(entry.last, "2024-03-01")

    def test_empty_entry_has_no_dates(self) -> None:
        entry = make_entry()
        self.assertEqual((entry.first, entry.last, entry.total_seconds), ("", "", 0))

    def test_identified_follows_the_title(self) -> None:
        self.assertTrue(make_entry(title="X").identified)
        self.assertFalse(make_entry().identified)

    def test_has_flag(self) -> None:
        entry = make_entry()
        entry.flags.append(FLAG_NO_PLAYTIME)
        self.assertTrue(entry.has_flag(FLAG_NO_PLAYTIME))
        self.assertFalse(entry.has_flag(FLAG_OVER_24H))


class LabelTests(unittest.TestCase):
    def test_identified_entries_use_their_title(self) -> None:
        entries = [make_entry("A", "Alpha"), make_entry("B", "Beta")]
        self.assertEqual([entry.label for entry in label_entries(entries)], ["Alpha", "Beta"])

    def test_unidentified_entries_are_numbered_in_order(self) -> None:
        entries = [make_entry("A", "Alpha"), make_entry("B"), make_entry("C")]
        self.assertEqual(
            [entry.label for entry in label_entries(entries)],
            ["Alpha", "未识别-01", "未识别-02"],
        )

    def test_numbering_template(self) -> None:
        self.assertEqual(UNIDENTIFIED_LABEL % 3, "未识别-03")

    def test_flag_is_added_exactly_once(self) -> None:
        entry = make_entry("B")
        label_entries([entry])
        label_entries([entry])
        self.assertEqual(entry.flags.count(FLAG_UNIDENTIFIED), 1)

    def test_returns_the_same_objects(self) -> None:
        entries = [make_entry("A", "Alpha")]
        self.assertIs(label_entries(entries)[0], entries[0])

    def test_empty_input(self) -> None:
        self.assertEqual(label_entries([]), [])


class FormatDurationTests(unittest.TestCase):
    def test_hours_and_minutes(self) -> None:
        self.assertEqual(format_duration(12705), "3 小时 31 分")

    def test_exact_hour(self) -> None:
        self.assertEqual(format_duration(3600), "1 小时 0 分")

    def test_minutes_only(self) -> None:
        self.assertEqual(format_duration(1095), "18 分")

    def test_under_a_minute_rounds_down(self) -> None:
        self.assertEqual(format_duration(59), "0 分")

    def test_zero(self) -> None:
        self.assertEqual(format_duration(0), "0 分")


class LoadResultTests(unittest.TestCase):
    @staticmethod
    def _result() -> LoadResult:
        return LoadResult(
            path=Path("x"),
            entries=[
                make_entry("A", "Alpha", [("2024-01-01", 60)]),
                make_entry("B", days=[("2024-01-02", 120)]),
            ],
        )

    def test_total_seconds(self) -> None:
        self.assertEqual(self._result().total_seconds, 180)

    def test_counts(self) -> None:
        result = self._result()
        self.assertEqual((result.identified_count, result.unidentified_count), (1, 1))

    def test_empty_result(self) -> None:
        result = LoadResult(path=Path("x"))
        self.assertEqual(
            (result.total_seconds, result.identified_count, result.unidentified_count),
            (0, 0, 0),
        )


class FlagLabelTests(unittest.TestCase):
    def test_every_flag_has_a_human_label(self) -> None:
        for flag in (
            FLAG_UNIDENTIFIED,
            FLAG_NO_PLAYTIME,
            FLAG_OVER_24H,
            FLAG_TOTAL_MISMATCH,
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, FLAG_LABELS)
                self.assertTrue(FLAG_LABELS[flag])


if __name__ == "__main__":
    unittest.main()
