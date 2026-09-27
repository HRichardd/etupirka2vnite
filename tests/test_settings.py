"""阶段 1 自测：设置读写。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from app import settings

from .tmpdir import make_temp_dir


class SettingsCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.json"
        patcher = mock.patch.object(settings, "settings_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)


class LoadTests(SettingsCase):
    def test_defaults_when_file_missing(self) -> None:
        self.assertEqual(
            settings.load(), {"db_path": "", "recent": [], "export_dir": ""}
        )

    def test_roundtrip(self) -> None:
        settings.save({"db_path": r"D:\gal", "recent": [r"D:\gal"], "export_dir": "out"})
        data = settings.load()
        self.assertEqual(data["db_path"], r"D:\gal")
        self.assertEqual(data["recent"], [r"D:\gal"])
        self.assertEqual(data["export_dir"], "out")

    def test_corrupted_json_falls_back_to_defaults(self) -> None:
        self.path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(settings.load()["db_path"], "")

    def test_non_dict_json_falls_back_to_defaults(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(
            settings.load(), {"db_path": "", "recent": [], "export_dir": ""}
        )

    def test_wrong_types_are_coerced(self) -> None:
        self.path.write_text(
            json.dumps({"db_path": 5, "recent": "oops", "export_dir": None}),
            encoding="utf-8",
        )
        data = settings.load()
        self.assertEqual(data["db_path"], "5")
        self.assertEqual(data["recent"], [])
        self.assertEqual(data["export_dir"], "")

    def test_recent_filters_junk_and_dedupes(self) -> None:
        self.path.write_text(
            json.dumps({"recent": ["a", "a", 7, "", None, "b"]}), encoding="utf-8"
        )
        self.assertEqual(settings.load()["recent"], ["a", "b"])

    def test_save_failure_returns_false_instead_of_raising(self) -> None:
        # 让 settings 的父路径是一个文件 → 写入必然失败
        self.path.write_text("occupied", encoding="utf-8")
        with mock.patch.object(
            settings, "settings_file", return_value=self.path / "sub" / "settings.json"
        ):
            self.assertFalse(settings.save({"db_path": "x"}))


class RememberTests(SettingsCase):
    def test_inserts_at_front(self) -> None:
        data = {"recent": ["b", "c"]}
        settings.remember_db(data, "a")
        self.assertEqual(data["recent"], ["a", "b", "c"])
        self.assertEqual(data["db_path"], "a")

    def test_existing_entry_moves_to_front_without_duplicating(self) -> None:
        data = {"recent": ["a", "b", "c"]}
        settings.remember_db(data, "c")
        self.assertEqual(data["recent"], ["c", "a", "b"])

    def test_truncates_to_max_recent(self) -> None:
        data = {"recent": []}
        for index in range(8):
            settings.remember_db(data, "p%d" % index)
        self.assertEqual(len(data["recent"]), settings.MAX_RECENT)
        self.assertEqual(data["recent"][0], "p7")

    def test_survives_missing_recent_key(self) -> None:
        data = {}
        settings.remember_db(data, "a")
        self.assertEqual(data["recent"], ["a"])


if __name__ == "__main__":
    unittest.main()
