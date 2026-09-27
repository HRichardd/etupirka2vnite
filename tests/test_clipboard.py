"""阶段 2 自测：剪贴板读写。

注意：``ClipboardRoundTripTests`` 会**覆盖系统剪贴板内容**——这是验证
「真的写进去了」的唯一办法。
"""

from __future__ import annotations

import sys
import unittest

from app import clipboard

ON_WINDOWS = sys.platform == "win32"


class ContractTests(unittest.TestCase):
    def test_available_matches_platform(self) -> None:
        self.assertEqual(clipboard.available(), ON_WINDOWS)

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(clipboard.ClipboardError):
            clipboard.copy_text("")


@unittest.skipUnless(ON_WINDOWS, "仅 Windows 有剪贴板实现")
class ClipboardRoundTripTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        sample = '{"timers":[],"dailyPlayTimes":[{"date":"2024-01-01","playTime":1000}]}'
        self.assertEqual(clipboard.copy_text(sample), "win32")
        self.assertEqual(clipboard.read_text(), sample)

    def test_unicode_round_trip(self) -> None:
        sample = "テスト・中文・絵文字 🎮"
        clipboard.copy_text(sample)
        self.assertEqual(clipboard.read_text(), sample)

    def test_overwrites_previous_content(self) -> None:
        clipboard.copy_text("first")
        clipboard.copy_text("second")
        self.assertEqual(clipboard.read_text(), "second")

    def test_long_payload_round_trip(self) -> None:
        sample = "x" * 200000
        clipboard.copy_text(sample)
        self.assertEqual(clipboard.read_text(), sample)


if __name__ == "__main__":
    unittest.main()
