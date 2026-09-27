"""阶段 2 自测：Vnite 载荷的生成与校验。"""

from __future__ import annotations

import json
import unittest

from app import vnite_payload as vp
from app.model import Day, Entry


def entry_with(days) -> Entry:
    return Entry(uid="UID", title="T", days=[Day(date, seconds) for date, seconds in days])


def payload_with(daily) -> dict:
    return {"timers": [], "dailyPlayTimes": daily}


class BuildTests(unittest.TestCase):
    def test_shape_is_exactly_two_keys(self) -> None:
        payload = vp.build(entry_with([("2024-01-01", 3600)]))
        self.assertEqual(set(payload), {"timers", "dailyPlayTimes"})
        self.assertEqual(payload["timers"], [])

    def test_seconds_become_milliseconds(self) -> None:
        payload = vp.build(entry_with([("2024-01-01", 12705)]))
        self.assertEqual(
            payload["dailyPlayTimes"], [{"date": "2024-01-01", "playTime": 12705000}]
        )

    def test_each_item_has_exactly_two_keys(self) -> None:
        payload = vp.build(entry_with([("2024-01-01", 60)]))
        self.assertEqual(set(payload["dailyPlayTimes"][0]), {"date", "playTime"})

    def test_entry_without_days(self) -> None:
        self.assertEqual(vp.build(entry_with([]))["dailyPlayTimes"], [])

    def test_dumps_is_compact_and_valid_json(self) -> None:
        text = vp.dumps(vp.build(entry_with([("2024-01-01", 60)])))
        self.assertNotIn(" ", text)
        self.assertEqual(
            json.loads(text)["dailyPlayTimes"][0]["playTime"], 60000
        )


class ValidateTests(unittest.TestCase):
    def test_accepts_good_payload(self) -> None:
        result = vp.validate(payload_with([{"date": "2024-02-29", "playTime": 1000}]))
        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])

    def test_rejects_non_object(self) -> None:
        self.assertFalse(vp.validate([1, 2]).ok)
        self.assertFalse(vp.validate("nope").ok)

    def test_rejects_extra_top_level_key(self) -> None:
        self.assertFalse(
            vp.validate({"timers": [], "dailyPlayTimes": [], "extra": 1}).ok
        )

    def test_rejects_missing_top_level_key(self) -> None:
        self.assertFalse(vp.validate({"timers": []}).ok)

    def test_rejects_non_list_members(self) -> None:
        self.assertFalse(vp.validate({"timers": {}, "dailyPlayTimes": []}).ok)
        self.assertFalse(vp.validate({"timers": [], "dailyPlayTimes": {}}).ok)

    def test_rejects_extra_key_in_item(self) -> None:
        result = vp.validate(
            payload_with([{"date": "2024-01-01", "playTime": 1, "extra": 2}])
        )
        self.assertFalse(result.ok)

    def test_rejects_impossible_dates(self) -> None:
        for bad in ("2024-13-45", "2024-02-30", "2023-02-29", "2024-1-1", "20240101", ""):
            with self.subTest(date=bad):
                self.assertFalse(
                    vp.validate(payload_with([{"date": bad, "playTime": 1}])).ok
                )

    def test_accepts_leap_day(self) -> None:
        self.assertTrue(
            vp.validate(payload_with([{"date": "2024-02-29", "playTime": 1}])).ok
        )

    def test_rejects_non_positive_or_non_numeric_playtime(self) -> None:
        for bad in (0, -1, 0.0, float("nan"), float("inf"), True, "60", None):
            with self.subTest(playTime=bad):
                self.assertFalse(
                    vp.validate(payload_with([{"date": "2024-01-01", "playTime": bad}])).ok
                )

    def test_rejects_duplicate_date(self) -> None:
        result = vp.validate(
            payload_with(
                [
                    {"date": "2024-01-01", "playTime": 1000},
                    {"date": "2024-01-01", "playTime": 2000},
                ]
            )
        )
        self.assertFalse(result.ok)
        self.assertIn("重复", result.summary())

    def test_warns_on_over_24_hours_but_still_ok(self) -> None:
        result = vp.validate(
            payload_with([{"date": "2024-01-01", "playTime": 25 * 3600 * 1000}])
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("24 小时", result.warnings[0])

    def test_warns_on_empty_daily_list(self) -> None:
        result = vp.validate(payload_with([]))
        self.assertTrue(result.ok)
        self.assertTrue(result.warnings)

    def test_rejects_unparsable_timer(self) -> None:
        result = vp.validate(
            {"timers": [{"start": "nope", "end": "nope"}], "dailyPlayTimes": []}
        )
        self.assertFalse(result.ok)

    def test_rejects_timer_with_extra_key(self) -> None:
        result = vp.validate(
            {
                "timers": [
                    {"start": "2024-01-01T00:00:00", "end": "2024-01-01T01:00:00", "z": 1}
                ],
                "dailyPlayTimes": [],
            }
        )
        self.assertFalse(result.ok)

    def test_accepts_valid_timers(self) -> None:
        result = vp.validate(
            {
                "timers": [
                    {"start": "2024-01-01T00:00:00", "end": "2024-01-01T01:00:00"}
                ],
                "dailyPlayTimes": [],
            }
        )
        self.assertTrue(result.ok)


class PrepareTests(unittest.TestCase):
    def test_prepare_returns_pasteable_text(self) -> None:
        text, validation = vp.prepare(
            entry_with([("2026-08-23", 12705), ("2026-08-24", 8790)])
        )
        self.assertTrue(validation.ok)
        payload = json.loads(text)
        self.assertEqual(payload["timers"], [])
        self.assertEqual(
            [item["playTime"] for item in payload["dailyPlayTimes"]],
            [12705000, 8790000],
        )

    def test_prepare_catches_bad_day_before_pasting(self) -> None:
        bad = Entry(uid="UID", title="T", days=[Day("2024-02-30", 60)])
        _text, validation = vp.prepare(bad)
        self.assertFalse(validation.ok)


if __name__ == "__main__":
    unittest.main()
