"""阶段 3 自测：别名表。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from app import aliases

from .tmpdir import make_temp_dir


class AliasCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "aliases.json"
        patcher = mock.patch.object(aliases, "aliases_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)


class LoadTests(AliasCase):
    def test_empty_when_file_missing(self) -> None:
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_corrupted_json_falls_back(self) -> None:
        self.path.write_text("{{{ not json", encoding="utf-8")
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_non_dict_falls_back(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_wrong_aliases_type_falls_back(self) -> None:
        self.path.write_text(json.dumps({"aliases": "nope"}), encoding="utf-8")
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_keeps_only_valid_pairs(self) -> None:
        self.path.write_text(
            json.dumps({"aliases": {"a": "Alpha", "b": "   ", "": "x", "c": 7, "d": "Beta"}}),
            encoding="utf-8",
        )
        self.assertEqual(aliases.mapping(aliases.load()), {"a": "Alpha", "d": "Beta"})

    def test_strips_surrounding_whitespace(self) -> None:
        self.path.write_text(
            json.dumps({"aliases": {"a": "  Alpha  "}}), encoding="utf-8"
        )
        self.assertEqual(aliases.mapping(aliases.load()), {"a": "Alpha"})


class SetTests(AliasCase):
    def test_set_and_get(self) -> None:
        state = aliases.load()
        aliases.set_alias(state, "uid1", "My Game")
        self.assertEqual(aliases.get(state, "uid1"), "My Game")
        self.assertEqual(aliases.count(state), 1)

    def test_blank_name_removes_the_alias(self) -> None:
        state = aliases.load()
        aliases.set_alias(state, "uid1", "My Game")
        aliases.set_alias(state, "uid1", "   ")
        self.assertEqual(aliases.mapping(state), {})

    def test_empty_uid_is_a_noop(self) -> None:
        state = aliases.load()
        aliases.set_alias(state, "", "X")
        self.assertEqual(aliases.mapping(state), {})

    def test_remove_alias(self) -> None:
        state = aliases.load()
        aliases.set_alias(state, "uid1", "X")
        aliases.remove_alias(state, "uid1")
        self.assertEqual(aliases.mapping(state), {})

    def test_remove_unknown_uid_is_safe(self) -> None:
        state = aliases.load()
        aliases.remove_alias(state, "nope")
        self.assertEqual(aliases.mapping(state), {})

    def test_repairs_broken_aliases_field(self) -> None:
        state = {"aliases": "broken"}
        aliases.set_alias(state, "uid1", "X")
        self.assertEqual(aliases.mapping(state), {"uid1": "X"})

    def test_get_unknown_returns_default(self) -> None:
        self.assertEqual(aliases.get(aliases.load(), "nope", "fallback"), "fallback")

    def test_roundtrip_through_disk(self) -> None:
        state = aliases.load()
        aliases.set_alias(state, "uid1", "とける風花とシロうさぎ")
        self.assertTrue(aliases.save(state))
        self.assertEqual(
            aliases.get(aliases.load(), "uid1"), "とける風花とシロうさぎ"
        )

    def test_save_failure_returns_false_instead_of_raising(self) -> None:
        self.path.write_text("occupied", encoding="utf-8")
        with mock.patch.object(
            aliases, "aliases_file", return_value=self.path / "sub" / "aliases.json"
        ):
            self.assertFalse(aliases.save(aliases.load()))

    def test_save_writes_clean_json(self) -> None:
        aliases.save({"aliases": {"uid1": "X", "": "junk", "uid2": "  "}})
        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(written["aliases"], {"uid1": "X"})
        self.assertEqual(written["version"], aliases.FORMAT_VERSION)


if __name__ == "__main__":
    unittest.main()
