"""阶段 5 自测：打包后的自检模块。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from app import paths, selfcheck

from . import make_fixture
from .tmpdir import make_temp_dir


class SelfCheckCase(unittest.TestCase):
    """把全部运行时路径关进临时目录，绝不碰真实配置。"""

    def setUp(self) -> None:
        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

        # 把「程序目录」也指到临时目录，否则 app_dir() 还是真实工程根，
        # next_to_executable 的判定就自相矛盾了
        app_patcher = mock.patch.object(paths, "app_dir", return_value=self.dir)
        app_patcher.start()
        self.addCleanup(app_patcher.stop)

        for attr, filename in (
            ("settings_file", "settings.json"),
            ("aliases_file", "aliases.json"),
            ("progress_file", "progress.json"),
            ("error_log_file", "error.log"),
        ):
            patcher = mock.patch.object(paths, attr, return_value=self.dir / filename)
            patcher.start()
            self.addCleanup(patcher.stop)

        data_patcher = mock.patch.object(paths, "data_dir", return_value=self.dir)
        data_patcher.start()
        self.addCleanup(data_patcher.stop)


class CollectTests(SelfCheckCase):
    def test_reports_the_running_environment(self) -> None:
        report = selfcheck.collect()
        self.assertEqual(report["frozen"], paths.is_frozen())
        self.assertEqual(report["app_dir"], str(paths.app_dir()))
        self.assertEqual(report["data_dir"], str(self.dir))
        self.assertTrue(report["data_dir_writable"])

    def test_every_config_file_is_next_to_the_executable(self) -> None:
        report = selfcheck.collect()
        self.assertEqual(len(report["files"]), 4)
        for label, info in report["files"].items():
            with self.subTest(file=label):
                self.assertTrue(info["next_to_executable"])
                self.assertTrue(info["path"].startswith(str(self.dir)))

    def test_missing_files_are_reported_as_absent(self) -> None:
        report = selfcheck.collect()
        self.assertFalse(report["files"]["settings"]["exists"])

    def test_reads_the_stored_config(self) -> None:
        from app import aliases, progress, settings

        settings.save({"db_path": r"D:\gal", "recent": [r"D:\gal"], "export_dir": ""})
        aliases.save({"aliases": {"uid1": "Name"}})
        state = progress.load()
        progress.mark(state, "uid1")
        progress.save(state)

        report = selfcheck.collect()
        self.assertEqual(report["config"]["db_path"], r"D:\gal")
        self.assertEqual(report["config"]["aliases"], 1)
        self.assertEqual(report["config"]["migrated"], 1)

    def test_loads_the_given_data_source(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        report = selfcheck.collect(str(self.dir))

        source = report["source"]
        self.assertTrue(source["checked"])
        self.assertTrue(source["ok"])
        self.assertEqual(source["entry_count"], 7)
        self.assertEqual(source["total_seconds"], 100720)
        self.assertEqual(source["identified"], 6)
        self.assertEqual(source["unidentified"], 1)

    def test_reports_a_bad_data_source_instead_of_raising(self) -> None:
        report = selfcheck.collect(str(self.dir / "nope"))
        self.assertTrue(report["source"]["checked"])
        self.assertFalse(report["source"]["ok"])
        self.assertIn("找不到路径", report["source"]["error"])

    def test_skips_when_there_is_no_source_at_all(self) -> None:
        with mock.patch.object(paths, "find_local_user_db", return_value=None):
            report = selfcheck.collect()
        self.assertFalse(report["source"]["checked"])
        self.assertIn("没有可用的数据源", report["source"]["reason"])

    def test_falls_back_to_the_local_user_db(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        with mock.patch.object(
            paths, "find_local_user_db", return_value=self.dir / "user.db"
        ):
            report = selfcheck.collect()
        self.assertTrue(report["source"]["ok"])
        self.assertEqual(report["source"]["entry_count"], 7)

    def test_unwritable_data_dir_is_reported_not_raised(self) -> None:
        blocker = self.dir / "blocker"
        blocker.write_text("x", encoding="utf-8")
        with mock.patch.object(paths, "data_dir", return_value=blocker / "sub"):
            report = selfcheck.collect()
        self.assertFalse(report["data_dir_writable"])
        self.assertTrue(report.get("data_dir_error"))


class RenderTests(SelfCheckCase):
    def test_contains_the_environment_and_config_sections(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        text = selfcheck.render(selfcheck.collect(str(self.dir)))

        self.assertIn("自检报告", text)
        self.assertIn("打包运行", text)
        self.assertIn("== 配置文件 ==", text)
        self.assertIn("== 已记住的配置 ==", text)
        self.assertIn("== 数据源读取 ==", text)
        self.assertIn("条目数     : 7", text)
        self.assertIn("总时长     : 100720 秒", text)

    def test_renders_a_skipped_source(self) -> None:
        with mock.patch.object(paths, "find_local_user_db", return_value=None):
            text = selfcheck.render(selfcheck.collect())
        self.assertIn("跳过", text)


class MainTests(SelfCheckCase):
    def test_writes_both_reports_and_returns_zero(self) -> None:
        target = self.dir / "sc.txt"
        code = selfcheck.main(["--selfcheck", "--out", str(target)])

        self.assertEqual(code, 0)
        self.assertTrue(target.exists())
        self.assertIn("自检报告", target.read_text(encoding="utf-8"))

        payload = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertIn("app_dir", payload)
        self.assertIn("source", payload)

    def test_default_output_lands_next_to_the_executable(self) -> None:
        code = selfcheck.main(["--selfcheck"])
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / selfcheck.REPORT_NAME).exists())

    def test_unwritable_output_returns_two(self) -> None:
        blocker = self.dir / "blocker"
        blocker.write_text("x", encoding="utf-8")
        code = selfcheck.main(["--selfcheck", "--out", str(blocker / "sub" / "sc.txt")])
        self.assertEqual(code, 2)

    def test_unwritable_data_dir_returns_three(self) -> None:
        blocker = self.dir / "blocker"
        blocker.write_text("x", encoding="utf-8")
        with mock.patch.object(paths, "data_dir", return_value=blocker / "sub"):
            code = selfcheck.main(["--selfcheck", "--out", str(self.dir / "sc.txt")])
        self.assertEqual(code, 3)

    def test_accepts_an_explicit_database(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        target = self.dir / "sc.txt"
        selfcheck.main(["--selfcheck", "--db", str(self.dir), "--out", str(target)])
        self.assertIn("条目数     : 7", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
