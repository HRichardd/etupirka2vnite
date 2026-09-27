"""阶段 1 自测：界面能构建、能加载数据源、筛选与选中正确。

无头冒烟测试——建窗口、跑逻辑、销毁，**不进入 mainloop**。
"""

from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path
from typing import Any, List, Optional
from unittest import mock

from tkinter import ttk

from app import aliases, exporters, gui, model, paths, progress, settings
from app.model import FLAG_UNIDENTIFIED

from . import make_fixture
from .tmpdir import make_temp_dir


def write_minimal_ico(path: Path, size: int = 16) -> None:
    """写一个合法的 32bpp ICO，用来验证图标加载路径真的能跑通。"""
    pixels = b"\x40\x80\xc0\xff" * (size * size)  # BGRA
    info = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0
    )
    mask = b"\x00" * (((size + 31) // 32) * 4 * size)
    image = info + pixels + mask
    directory = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), 6 + 16)
    path.write_bytes(directory + entry + image)


def find_widget(parent: Any, cls: type, text: Optional[str] = None) -> Any:
    """在控件树里按类型（可再按文本）找一个控件。"""
    for child in parent.winfo_children():
        if isinstance(child, cls):
            if text is None or str(child.cget("text")) == text:
                return child
        found = find_widget(child, cls, text)
        if found is not None:
            return found
    return None


def _tk_available() -> bool:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:  # noqa: BLE001 - 没有显示环境就整体跳过
        return False


TK_AVAILABLE = _tk_available()


@unittest.skipUnless(TK_AVAILABLE, "当前环境无法创建 Tk 窗口")
class GuiCase(unittest.TestCase):
    def setUp(self) -> None:
        import tkinter

        tmp = make_temp_dir()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

        # 设置与别名表都关进临时目录，测试之间互不影响、也不碰真实文件
        for module, attr, filename in (
            (settings, "settings_file", "settings.json"),
            (aliases, "aliases_file", "aliases.json"),
        ):
            patcher = mock.patch.object(module, attr, return_value=self.dir / filename)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.tk = tkinter.Tk()
        self.tk.withdraw()
        self.addCleanup(self._destroy_root)

    def _destroy_root(self) -> None:
        try:
            self.tk.destroy()
        except Exception:  # noqa: BLE001 - 销毁失败不该影响测试结论
            pass

    def build_app(self) -> gui.MigratorApp:
        return gui.MigratorApp(self.tk)


class EmptyStateTests(GuiCase):
    def test_starts_in_empty_state(self) -> None:
        app = self.build_app()
        self.assertIsNone(app.result)
        self.assertEqual(app.entries, [])
        self.assertIn("请选择", app.empty_message.cget("text"))

    def test_bad_source_is_reported_without_crashing(self) -> None:
        app = self.build_app()
        self.assertFalse(app.load_source(str(self.dir / "nope"), notify=False))
        self.assertEqual(app.entries, [])
        self.assertIn("找不到路径", app.empty_message.cget("text"))

    def test_directory_without_user_db(self) -> None:
        app = self.build_app()
        self.assertFalse(app.load_source(str(self.dir), notify=False))
        self.assertIn("没有 user.db", app.empty_message.cget("text"))

    def test_reload_without_source_keeps_empty_state(self) -> None:
        app = self.build_app()
        app.reload()
        self.assertEqual(app.entries, [])


class LoadSourceTests(GuiCase):
    def test_loads_directory(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        self.assertTrue(app.load_source(str(self.dir)))
        self.assertEqual(len(app.entries), 7)
        self.assertEqual(len(app.visible), 7)
        self.assertIn("已迁移 0 / 7 条", app.status.cget("text"))

    def test_loads_single_db_file(self) -> None:
        db = make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        self.assertTrue(app.load_source(str(db)))
        self.assertEqual(len(app.entries), 7)

    def test_remembers_last_source(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))
        data = settings.load()
        self.assertEqual(data["db_path"], str(self.dir))
        self.assertEqual(data["recent"][0], str(self.dir))

    def test_source_label_shows_path(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))
        self.assertEqual(app.source_label.cget("text"), str(self.dir))

    def test_autoloads_remembered_source(self) -> None:
        import tkinter

        make_fixture.build_standard(self.dir / "user.db")
        first = self.build_app()
        first.load_source(str(self.dir))

        # 换一个 Tk 根，模拟「关掉再打开」
        other_root = tkinter.Tk()
        other_root.withdraw()
        self.addCleanup(other_root.destroy)
        second = gui.MigratorApp(other_root)
        self.assertIsNotNone(second.result)
        self.assertEqual(len(second.entries), 7)

    def test_recent_menu_lists_previous_sources(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))
        last = app.recent_menu.index("end")
        self.assertIsNotNone(last)
        labels = [
            app.recent_menu.entrycget(index, "label")
            for index in range(int(last) + 1)
            if app.recent_menu.type(index) == "command"
        ]
        self.assertIn(str(self.dir), labels)


class FilterTests(GuiCase):
    def setUp(self) -> None:
        super().setUp()
        make_fixture.build_standard(self.dir / "user.db")
        self.app = self.build_app()
        self.app.load_source(str(self.dir))

    def test_renders_one_row_per_entry(self) -> None:
        self.assertEqual(len(self.app._rows), 7)
        self.assertEqual(len(self.app.rows_frame.winfo_children()), 7)

    def test_filter_all(self) -> None:
        self.app._filter.set(gui.FILTER_ALL)
        self.app.apply_filter()
        self.assertEqual(len(self.app.visible), 7)

    def test_filter_unidentified(self) -> None:
        self.app._filter.set(gui.FILTER_UNIDENTIFIED)
        self.app.apply_filter()
        self.assertEqual([entry.label for entry in self.app.visible], ["未识别-01"])
        self.assertEqual(len(self.app._rows), 1)

    def test_filter_pending_equals_all_before_phase_two(self) -> None:
        self.app._filter.set(gui.FILTER_PENDING)
        self.app.apply_filter()
        self.assertEqual(len(self.app.visible), 7)

    def test_filter_with_no_match_shows_hint(self) -> None:
        self.app.apply_filter()
        self.app.migrated = {entry.uid for entry in self.app.entries}
        self.app._filter.set(gui.FILTER_PENDING)
        self.app.apply_filter()
        self.assertEqual(self.app.visible, [])
        self.assertIn("筛选条件", self.app.empty_message.cget("text"))


class SelectionTests(GuiCase):
    def setUp(self) -> None:
        super().setUp()
        make_fixture.build_standard(self.dir / "user.db")
        self.app = self.build_app()
        self.app.load_source(str(self.dir))

    def _entry(self, uid: str) -> Any:
        return next(entry for entry in self.app.entries if entry.uid == uid)

    def test_select_updates_detail(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.select(entry)
        self.assertEqual(self.app.detail_title.cget("text"), "Alpha Game")
        self.assertIn("时长", self.app.detail_meta.cget("text"))
        self.assertEqual(self.app.detail_path.cget("text"), r"D:\games\alpha\alpha.exe")

    def test_select_marks_unidentified(self) -> None:
        orphan = next(
            entry for entry in self.app.entries if entry.has_flag(FLAG_UNIDENTIFIED)
        )
        self.app.select(orphan)
        self.assertIn("未识别", self.app.detail_flags.cget("text"))

    def test_select_marks_over_24h(self) -> None:
        self.app.select(self._entry("HUGE000000000001"))
        self.assertIn("24 小时", self.app.detail_flags.cget("text"))

    def test_clean_entry_reports_normal(self) -> None:
        self.app.select(self._entry("ALPHA000000000001"))
        self.assertEqual(self.app.detail_flags.cget("text"), "正常")

    def test_reload_clears_selection(self) -> None:
        self.app.select(self._entry("ALPHA000000000001"))
        self.app.reload()
        self.assertIsNone(self.app.selected)
        self.assertEqual(self.app.detail_title.cget("text"), "（未选择条目）")

    def test_switching_source_replaces_entries(self) -> None:
        other = make_fixture.create_db(
            self.dir / "other" / "user.db",
            games=[("ONLYONE000000001", "Only One", None, None, 0)],
            playtime=[("2024-01-01", "ONLYONE000000001", 60)],
        )
        self.assertTrue(self.app.load_source(str(other)))
        self.assertEqual(len(self.app.entries), 1)
        self.assertEqual(self.app.entries[0].label, "Only One")
        self.assertEqual(len(self.app._rows), 1)


class CopyTests(GuiCase):
    """一键复制与迁移状态。剪贴板和弹窗都被 mock 掉，不会动真实系统剪贴板。"""

    def setUp(self) -> None:
        super().setUp()
        make_fixture.build_standard(self.dir / "user.db")

        progress_patcher = mock.patch.object(
            progress, "progress_file", return_value=self.dir / "progress.json"
        )
        progress_patcher.start()
        self.addCleanup(progress_patcher.stop)

        box_patcher = mock.patch.object(gui, "messagebox")
        self.box = box_patcher.start()
        self.addCleanup(box_patcher.stop)

        self.copied: List[str] = []

        def fake_copy(text: str) -> str:
            self.copied.append(text)
            return "win32"

        clip_patcher = mock.patch.object(gui.clipboard, "copy_text", side_effect=fake_copy)
        clip_patcher.start()
        self.addCleanup(clip_patcher.stop)

        self.app = self.build_app()
        self.app.load_source(str(self.dir))

    def _entry(self, uid: str) -> Any:
        return next(entry for entry in self.app.entries if entry.uid == uid)

    # ---- 载荷 ----

    def test_copy_writes_the_expected_payload(self) -> None:
        self.app.copy_entry(self._entry("ALPHA000000000001"))
        self.assertEqual(len(self.copied), 1)
        payload = json.loads(self.copied[0])
        self.assertEqual(payload["timers"], [])
        self.assertEqual(
            payload["dailyPlayTimes"],
            [
                {"date": "2024-01-01", "playTime": 3600000},
                {"date": "2024-01-02", "playTime": 4200000},
            ],
        )

    def test_payload_passes_vnites_own_rules(self) -> None:
        from app import vnite_payload

        self.app.copy_entry(self._entry("ALPHA000000000001"))
        self.assertTrue(vnite_payload.validate(json.loads(self.copied[0])).ok)

    # ---- 状态 ----

    def test_copy_marks_migrated_and_reports(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.copy_entry(entry)
        self.assertIn(entry.uid, self.app.migrated)
        self.assertIn("已复制", self.app.status.cget("text"))

    def test_row_dot_turns_into_a_check(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.assertEqual(self.app._rows[entry.uid][1][0].cget("text"), "○")
        self.app.copy_entry(entry)
        self.assertEqual(self.app._rows[entry.uid][1][0].cget("text"), "✓")

    def test_state_is_written_to_disk(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.copy_entry(entry)
        self.assertEqual(progress.migrated_uids(progress.load()), {entry.uid})

    def test_state_survives_restart(self) -> None:
        import tkinter

        entry = self._entry("ALPHA000000000001")
        self.app.copy_entry(entry)

        other_root = tkinter.Tk()
        other_root.withdraw()
        self.addCleanup(other_root.destroy)
        second = gui.MigratorApp(other_root)
        self.assertIn(entry.uid, second.migrated)

    def test_status_counts_migrated(self) -> None:
        self.app.copy_entry(self._entry("ALPHA000000000001"))
        self.app.copy_entry(self._entry("HUGE000000000001"))
        self.app._update_status()
        self.assertIn("已迁移 2 / 7 条", self.app.status.cget("text"))

    def test_pending_filter_drops_the_copied_row(self) -> None:
        self.app._filter.set(gui.FILTER_PENDING)
        self.app.apply_filter()
        self.assertEqual(len(self.app.visible), 7)

        self.app.copy_entry(self._entry("ALPHA000000000001"))
        self.assertEqual(len(self.app.visible), 6)

    # ---- 右键菜单 ----

    def test_unmark_via_context_action(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.copy_entry(entry)
        self.app.select(entry)

        self.app._context_action("unmark")
        self.assertNotIn(entry.uid, self.app.migrated)
        self.assertEqual(self.app._rows[entry.uid][1][0].cget("text"), "○")
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_mark_via_context_action(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.select(entry)
        self.app._context_action("mark")
        self.assertIn(entry.uid, self.app.migrated)

    def test_context_action_without_selection_is_safe(self) -> None:
        self.app.selected = None
        self.app._context_action("copy")
        self.assertEqual(self.copied, [])

    def test_json_action_opens_the_payload_window(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.select(entry)
        with mock.patch.object(self.app, "_show_payload_window") as window:
            self.app._context_action("json")
        self.assertTrue(window.called)

    # ---- 失败路径 ----

    def test_invalid_payload_blocks_the_copy(self) -> None:
        entry = self._entry("ALPHA000000000001")
        entry.days = [model.Day("2024-02-30", 60)]

        self.app.copy_entry(entry)
        self.assertEqual(self.copied, [])
        self.assertNotIn(entry.uid, self.app.migrated)
        self.assertTrue(self.box.showerror.called)

    def test_clipboard_failure_offers_manual_copy(self) -> None:
        entry = self._entry("ALPHA000000000001")
        with mock.patch.object(
            gui.clipboard, "copy_text", side_effect=gui.clipboard.ClipboardError("被占用")
        ), mock.patch.object(self.app, "_show_payload_window") as window:
            self.app.copy_entry(entry)

        self.assertTrue(self.box.showwarning.called)
        self.assertTrue(window.called)
        self.assertNotIn(entry.uid, self.app.migrated)

    def test_progress_write_failure_is_surfaced(self) -> None:
        entry = self._entry("ALPHA000000000001")
        with mock.patch.object(progress, "save", return_value=False):
            self.app.copy_entry(entry)
        self.assertIn("未能写入磁盘", self.app.status.cget("text"))


class Phase3Case(GuiCase):
    """阶段 3 的共用夹具：进度、剪贴板、弹窗全部 mock 掉。"""

    def setUp(self) -> None:
        super().setUp()
        make_fixture.build_standard(self.dir / "user.db")

        progress_patcher = mock.patch.object(
            progress, "progress_file", return_value=self.dir / "progress.json"
        )
        progress_patcher.start()
        self.addCleanup(progress_patcher.stop)

        box_patcher = mock.patch.object(gui, "messagebox")
        self.box = box_patcher.start()
        self.addCleanup(box_patcher.stop)

        self.copied: List[str] = []

        def fake_copy(text: str) -> str:
            self.copied.append(text)
            return "win32"

        clip_patcher = mock.patch.object(gui.clipboard, "copy_text", side_effect=fake_copy)
        clip_patcher.start()
        self.addCleanup(clip_patcher.stop)

        self.app = self.build_app()
        self.app.load_source(str(self.dir))

    def _entry(self, uid: str) -> Any:
        return next(entry for entry in self.app.entries if entry.uid == uid)

    def _orphan(self) -> Any:
        return next(
            entry for entry in self.app.entries if entry.has_flag(FLAG_UNIDENTIFIED)
        )

    def _rename(self, entry: Any, value: Any) -> None:
        with mock.patch.object(gui.simpledialog, "askstring", return_value=value):
            self.app.rename_entry(entry)


class CopyNameTests(Phase3Case):
    """复制游戏名：三个入口，且不改动迁移状态。"""

    def test_via_method(self) -> None:
        self.app.copy_name(self._entry("ALPHA000000000001"))
        self.assertEqual(self.copied, ["Alpha Game"])
        self.assertIn("已复制游戏名", self.app.status.cget("text"))

    def test_via_context_action(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.select(entry)
        self.app._context_action("copy_name")
        self.assertEqual(self.copied, ["Alpha Game"])

    def test_via_detail_button(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.select(entry)
        self.assertEqual(str(self.app.copy_name_button.cget("state")), "normal")
        self.app.copy_name_button.invoke()
        self.assertEqual(self.copied, ["Alpha Game"])

    def test_button_disabled_before_any_selection(self) -> None:
        self.assertEqual(str(self.app.copy_name_button.cget("state")), "disabled")

    def test_button_back_to_disabled_when_source_reloads(self) -> None:
        self.app.select(self._entry("ALPHA000000000001"))
        self.app._show_empty("x")
        self.assertEqual(str(self.app.copy_name_button.cget("state")), "disabled")

    def test_via_ctrl_c(self) -> None:
        self.app.select(self._entry("ALPHA000000000001"))
        self.assertEqual(self.app._on_ctrl_c(None), "break")
        self.assertEqual(self.copied, ["Alpha Game"])

    def test_ctrl_c_yields_to_text_widgets(self) -> None:
        import tkinter

        self.app.select(self._entry("ALPHA000000000001"))
        text = tkinter.Text(self.tk)
        with mock.patch.object(self.tk, "focus_get", return_value=text):
            self.assertIsNone(self.app._on_ctrl_c(None))
        self.assertEqual(self.copied, [])

    def test_ctrl_c_with_no_selection_is_safe(self) -> None:
        self.app.selected = None
        self.assertIsNone(self.app._on_ctrl_c(None))
        self.assertEqual(self.copied, [])

    def test_does_not_change_migration_state(self) -> None:
        entry = self._entry("ALPHA000000000001")
        self.app.copy_name(entry)
        self.assertNotIn(entry.uid, self.app.migrated)
        self.assertEqual(progress.migrated_uids(progress.load()), set())
        self.assertEqual(self.app._rows[entry.uid][1][0].cget("text"), "○")

    def test_copies_the_label_for_unidentified_entries(self) -> None:
        self.app.copy_name(self._orphan())
        self.assertEqual(self.copied, ["未识别-01"])

    def test_failure_is_reported(self) -> None:
        entry = self._entry("ALPHA000000000001")
        with mock.patch.object(
            gui.clipboard, "copy_text", side_effect=gui.clipboard.ClipboardError("被占用")
        ):
            self.app.copy_name(entry)
        self.assertTrue(self.box.showerror.called)


class RenameTests(Phase3Case):
    def test_renames_an_unidentified_entry(self) -> None:
        orphan = self._orphan()
        self._rename(orphan, "真名")

        after = self._entry(orphan.uid)
        self.assertEqual(after.label, "真名")
        self.assertEqual(after.title_source, "alias")
        self.assertFalse(after.has_flag(FLAG_UNIDENTIFIED))
        self.assertEqual(aliases.mapping(aliases.load()), {orphan.uid: "真名"})

    def test_persists_across_restart(self) -> None:
        import tkinter

        orphan = self._orphan()
        self._rename(orphan, "真名")

        other_root = tkinter.Tk()
        other_root.withdraw()
        self.addCleanup(other_root.destroy)
        second = gui.MigratorApp(other_root)
        self.assertEqual(self._entry_of(second, orphan.uid).label, "真名")

    @staticmethod
    def _entry_of(app: Any, uid: str) -> Any:
        return next(entry for entry in app.entries if entry.uid == uid)

    def test_overrides_an_existing_title(self) -> None:
        self._rename(self._entry("ALPHA000000000001"), "改过的名字")
        self.assertEqual(self._entry("ALPHA000000000001").label, "改过的名字")
        self.assertEqual(self._entry("ALPHA000000000001").title_source, "alias")

    def test_blank_name_clears_the_alias(self) -> None:
        orphan = self._orphan()
        self._rename(orphan, "真名")
        self._rename(self._entry(orphan.uid), "   ")

        after = self._entry(orphan.uid)
        self.assertTrue(after.has_flag(FLAG_UNIDENTIFIED))
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_cancel_changes_nothing(self) -> None:
        orphan = self._orphan()
        self._rename(orphan, None)
        self.assertTrue(self._entry(orphan.uid).has_flag(FLAG_UNIDENTIFIED))
        self.assertEqual(aliases.mapping(aliases.load()), {})

    def test_keeps_the_selection_on_the_same_entry(self) -> None:
        orphan = self._orphan()
        self.app.select(orphan)
        self._rename(orphan, "真名")
        self.assertIsNotNone(self.app.selected)
        self.assertEqual(self.app.selected.uid, orphan.uid)

    def test_does_not_touch_migration_state(self) -> None:
        self._rename(self._orphan(), "真名")
        self.assertEqual(progress.migrated_uids(progress.load()), set())

    def test_unidentified_filter_shrinks_after_renaming(self) -> None:
        orphan = self._orphan()
        self.app._filter.set(gui.FILTER_UNIDENTIFIED)
        self.app.apply_filter()
        self.assertEqual(len(self.app.visible), 1)

        self._rename(orphan, "真名")

        self.app._filter.set(gui.FILTER_UNIDENTIFIED)
        self.app.apply_filter()
        self.assertEqual(self.app.visible, [])


class ExportTests(Phase3Case):
    def _export_to(self, target: Any) -> None:
        with mock.patch.object(gui.filedialog, "askdirectory", return_value=str(target)):
            self.app.export_entries()

    def test_writes_the_four_files(self) -> None:
        out = self.dir / "out"
        self._export_to(out)
        self.assertEqual({path.name for path in out.iterdir()}, set(exporters.GENERATED_FILES))
        self.assertIn("已导出 4 个文件", self.app.status.cget("text"))

    def test_remembers_the_directory(self) -> None:
        out = self.dir / "out"
        self._export_to(out)
        self.assertEqual(settings.load()["export_dir"], str(out))

    def test_cancel_changes_nothing(self) -> None:
        before = settings.load()["export_dir"]
        with mock.patch.object(gui.filedialog, "askdirectory", return_value=""):
            self.app.export_entries()
        self.assertEqual(settings.load()["export_dir"], before)
        self.assertFalse(self.box.showinfo.called)

    def test_without_a_source_it_reports_instead_of_crashing(self) -> None:
        self.app._show_empty("x")
        self.app.export_entries()
        self.assertTrue(self.box.showinfo.called)

    def test_failure_is_reported(self) -> None:
        blocker = self.dir / "blocker"
        blocker.write_text("x", encoding="utf-8")
        self._export_to(blocker / "sub")
        self.assertTrue(self.box.showerror.called)

    def test_does_not_delete_foreign_files(self) -> None:
        out = self.dir / "out"
        out.mkdir()
        keep = out / "我的笔记.txt"
        keep.write_text("keep", encoding="utf-8")

        self._export_to(out)

        self.assertTrue(keep.is_file())

    def test_export_carries_aliases_and_migration_state(self) -> None:
        orphan = self._orphan()
        self.app.copy_entry(self._entry("ALPHA000000000001"))
        self._rename(orphan, "真名")

        out = self.dir / "out"
        self._export_to(out)

        payload = json.loads((out / exporters.RAW_NAME).read_text(encoding="utf-8"))
        self.assertEqual(payload["aliases"], {orphan.uid: "真名"})
        migrated = [entry for entry in payload["entries"] if entry["migrated"]]
        self.assertEqual(len(migrated), 1)


class PolishTests(GuiCase):
    """阶段 4：窗口图标、异常兜底、配置目录回退提示。"""

    def setUp(self) -> None:
        super().setUp()
        self.log_path = self.dir / "error.log"
        log_patcher = mock.patch.object(
            paths, "error_log_file", return_value=self.log_path
        )
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

        box_patcher = mock.patch.object(gui, "messagebox")
        self.box = box_patcher.start()
        self.addCleanup(box_patcher.stop)

    # ---- 窗口基本属性 ----

    def test_window_title_and_minimum_size(self) -> None:
        self.build_app()
        self.assertEqual(self.tk.title(), gui.WINDOW_TITLE)
        self.assertEqual(self.tk.minsize(), (gui.MIN_WIDTH, gui.MIN_HEIGHT))

    # ---- 图标 ----

    def test_no_icon_by_default(self) -> None:
        app = self.build_app()
        self.assertIsNone(app.icon_source)

    def test_missing_icon_directory_is_fine(self) -> None:
        with mock.patch.object(gui.paths, "app_dir", return_value=self.dir / "nope"):
            app = self.build_app()
        self.assertIsNone(app.icon_source)

    def test_invalid_icon_file_is_ignored(self) -> None:
        (self.dir / gui.ICON_CANDIDATES[0]).write_bytes(b"definitely not an icon")
        with mock.patch.object(gui.paths, "app_dir", return_value=self.dir):
            app = self.build_app()
        self.assertIsNone(app.icon_source)

    def test_valid_icon_is_picked_up(self) -> None:
        write_minimal_ico(self.dir / gui.ICON_CANDIDATES[0])
        with mock.patch.object(gui.paths, "app_dir", return_value=self.dir):
            app = self.build_app()
        self.assertEqual(app.icon_source, self.dir / gui.ICON_CANDIDATES[0])

    def test_icon_search_starts_at_the_program_directory(self) -> None:
        self.assertEqual(
            gui.MigratorApp._icon_search_dirs()[0], gui.paths.app_dir()
        )

    # ---- 异常兜底 ----

    def test_unhandled_exception_is_logged_and_reported(self) -> None:
        app = self.build_app()
        try:
            raise ValueError("boom")
        except ValueError:
            app.root.report_callback_exception(*sys.exc_info())

        self.assertTrue(self.log_path.exists())
        text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("ValueError", text)
        self.assertIn("boom", text)
        self.assertTrue(self.box.showerror.called)

    def test_exception_log_appends_instead_of_overwriting(self) -> None:
        app = self.build_app()
        for _ in range(2):
            try:
                raise RuntimeError("again")
            except RuntimeError:
                app.root.report_callback_exception(*sys.exc_info())
        # 每次异常写一条 60 个等号的分隔行
        self.assertEqual(
            self.log_path.read_text(encoding="utf-8").count("=" * 60), 2
        )

    def test_exception_hook_still_reports_when_the_log_is_unwritable(self) -> None:
        app = self.build_app()
        blocker = self.dir / "blocker"
        blocker.write_text("x", encoding="utf-8")

        with mock.patch.object(
            gui.paths, "error_log_file", return_value=blocker / "sub" / "error.log"
        ):
            try:
                raise ValueError("still reported")
            except ValueError:
                app.root.report_callback_exception(*sys.exc_info())

        self.assertTrue(self.box.showerror.called)

    # ---- 配置目录回退 ----

    def test_status_mentions_the_fallback_config_dir(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))

        with mock.patch.object(
            gui.paths, "uses_fallback_dir", return_value=True
        ), mock.patch.object(
            gui.paths, "data_dir", return_value=Path("C:/elsewhere")
        ):
            app._update_status()

        self.assertIn("配置目录", app.status.cget("text"))
        self.assertIn("elsewhere", app.status.cget("text"))

    # ---- 其他交互细节 ----

    def test_mousewheel_without_rows_is_safe(self) -> None:
        app = self.build_app()
        app._on_mousewheel(mock.Mock(delta=120))

    def test_reload_uses_the_remembered_source(self) -> None:
        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))

        app.entries = []
        app.reload()

        self.assertEqual(len(app.entries), 7)

    def test_payload_window_shows_the_json(self) -> None:
        import tkinter

        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))
        entry = app.entries[1]
        app.show_payload(entry)
        self.tk.update_idletasks()

        window = find_widget(self.tk, tkinter.Toplevel)
        text = find_widget(window, tkinter.Text)
        self.assertIn('"dailyPlayTimes"', text.get("1.0", "end-1c"))
        self.assertIn(entry.label, window.title())

    def test_payload_window_retry_copies(self) -> None:
        import tkinter

        copied: List[str] = []

        def fake_copy(value: str) -> str:
            copied.append(value)
            return "win32"

        make_fixture.build_standard(self.dir / "user.db")
        app = self.build_app()
        app.load_source(str(self.dir))

        with mock.patch.object(gui.clipboard, "copy_text", side_effect=fake_copy):
            app.show_payload(app.entries[1])
            self.tk.update_idletasks()
            window = find_widget(self.tk, tkinter.Toplevel)
            find_widget(window, ttk.Button, "重试复制").invoke()

        self.assertEqual(len(copied), 1)
        self.assertIn("dailyPlayTimes", copied[0])


if __name__ == "__main__":
    unittest.main()
