"""阶段 2 自测：迁移状态的持久化。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from app import progress

from .tmpdir import make_temp_dir


class ProgressCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "progress.json"
        patcher = mock.patch.object(progress, "progress_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)


class LoadTests(ProgressCase):
    def test_empty_when_file_missing(self) -> None:
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_corrupted_json_falls_back(self) -> None:
        self.path.write_text("{{{ not json", encoding="utf-8")
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_non_dict_falls_back(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_wrong_entries_type_falls_back(self) -> None:
        self.path.write_text(json.dumps({"entries": "nope"}), encoding="utf-8")
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_drops_junk_uids_and_keeps_the_rest(self) -> None:
        self.path.write_text(
            json.dumps({"entries": {"a": {"migrated_at": "x"}, "": {}, "b": None}}),
            encoding="utf-8",
        )
        self.assertEqual(progress.migrated_uids(progress.load()), {"a", "b"})


class MarkTests(ProgressCase):
    def test_mark_then_unmark(self) -> None:
        state = progress.load()
        progress.mark(state, "uid1", when="2026-01-01T00:00:00")
        self.assertEqual(progress.migrated_uids(state), {"uid1"})
        self.assertEqual(progress.migrated_at(state, "uid1"), "2026-01-01T00:00:00")

        progress.unmark(state, "uid1")
        self.assertEqual(progress.migrated_uids(state), set())
        self.assertEqual(progress.migrated_at(state, "uid1"), "")

    def test_mark_records_a_timestamp_by_default(self) -> None:
        state = progress.load()
        progress.mark(state, "uid1")
        self.assertTrue(progress.migrated_at(state, "uid1"))

    def test_mark_with_empty_uid_is_a_noop(self) -> None:
        state = progress.load()
        progress.mark(state, "")
        self.assertEqual(progress.migrated_uids(state), set())

    def test_unmark_unknown_uid_is_safe(self) -> None:
        state = progress.load()
        progress.unmark(state, "nope")
        self.assertEqual(progress.migrated_uids(state), set())

    def test_mark_repairs_a_broken_entries_field(self) -> None:
        state = {"entries": "broken"}
        progress.mark(state, "uid1")
        self.assertEqual(progress.migrated_uids(state), {"uid1"})

    def test_roundtrip_through_disk(self) -> None:
        state = progress.load()
        progress.mark(state, "uid1", when="2026-01-01T00:00:00")
        self.assertTrue(progress.save(state))

        again = progress.load()
        self.assertEqual(progress.migrated_uids(again), {"uid1"})
        self.assertEqual(progress.migrated_at(again, "uid1"), "2026-01-01T00:00:00")

    def test_save_failure_returns_false_instead_of_raising(self) -> None:
        self.path.write_text("occupied", encoding="utf-8")
        with mock.patch.object(
            progress, "progress_file", return_value=self.path / "sub" / "progress.json"
        ):
            self.assertFalse(progress.save(progress.load()))

    def test_save_writes_clean_json(self) -> None:
        state = {"entries": {"uid1": {"migrated_at": "x"}, "": {}}}
        progress.save(state)
        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(written["entries"]), {"uid1"})
        self.assertEqual(written["version"], progress.FORMAT_VERSION)


if __name__ == "__main__":
    unittest.main()
