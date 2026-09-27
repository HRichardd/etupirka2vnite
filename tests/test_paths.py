"""阶段 0 自测：运行目录解析（尤其是 PyInstaller onefile 的坑）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from app import paths

from .tmpdir import make_temp_dir


class SourceModeTests(unittest.TestCase):
    def setUp(self) -> None:
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)

    def test_app_dir_is_project_root(self) -> None:
        expected = Path(paths.__file__).resolve().parent.parent
        self.assertEqual(paths.app_dir(), expected)

    def test_data_dir_is_writable_directory(self) -> None:
        directory = paths.data_dir()
        self.assertTrue(directory.is_dir())
        probe = directory / ".probe-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def test_config_files_live_in_data_dir(self) -> None:
        base = paths.data_dir()
        self.assertEqual(paths.settings_file(), base / "settings.json")
        self.assertEqual(paths.aliases_file(), base / "aliases.json")
        self.assertEqual(paths.progress_file(), base / "progress.json")
        self.assertEqual(paths.default_export_dir(), base / "out")
        self.assertEqual(paths.error_log_file(), base / "error.log")

    def test_not_frozen_by_default(self) -> None:
        self.assertFalse(paths.is_frozen())


class FrozenModeTests(unittest.TestCase):
    """打包后 ``__file__`` 指向临时解包目录，路径必须以 exe 为准。"""

    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exe = self.root / "etupirka2vnite.exe"
        self.exe.write_bytes(b"MZ")

        patcher = mock.patch.object(sys, "frozen", True, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        exec_patcher = mock.patch.object(sys, "executable", str(self.exe))
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)

        paths.reset_cache()
        self.addCleanup(paths.reset_cache)

    def test_app_dir_follows_executable(self) -> None:
        self.assertTrue(paths.is_frozen())
        self.assertEqual(paths.app_dir(), self.root)

    def test_data_dir_is_next_to_exe(self) -> None:
        self.assertEqual(paths.data_dir(), self.root)
        self.assertFalse(paths.uses_fallback_dir())

    def test_find_local_user_db(self) -> None:
        self.assertIsNone(paths.find_local_user_db())
        (self.root / "user.db").write_bytes(b"SQLite format 3\x00")
        self.assertEqual(paths.find_local_user_db(), self.root / "user.db")


class FallbackTests(unittest.TestCase):
    """exe 所在目录不可写时，配置要落到 %APPDATA%，而不是静默失败。"""

    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.appdata = Path(tmp.name)
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)

    def test_falls_back_when_app_dir_is_not_writable(self) -> None:
        missing = self.appdata / "definitely" / "missing" / "dir"
        with mock.patch.object(paths, "app_dir", return_value=missing), mock.patch.dict(
            os.environ, {"APPDATA": str(self.appdata)}
        ):
            directory = paths.data_dir()

        self.assertEqual(directory, self.appdata / paths.APP_NAME)
        self.assertTrue(directory.is_dir())
        self.assertTrue(paths.uses_fallback_dir())

    def test_fallback_is_cached(self) -> None:
        missing = self.appdata / "nope"
        with mock.patch.object(paths, "app_dir", return_value=missing), mock.patch.dict(
            os.environ, {"APPDATA": str(self.appdata)}
        ):
            self.assertEqual(paths.data_dir(), paths.data_dir())


if __name__ == "__main__":
    unittest.main()
