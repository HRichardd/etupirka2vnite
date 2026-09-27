"""tkinter 界面。

**阶段 1 范围**：窗口骨架、数据源栏（选择目录 / 选择 user.db / 最近 / 重新读取）、
空状态引导页、可滚动条目列表、筛选、详情面板、状态栏。

「复制」按钮已按 §3.1 摆好但**暂时禁用**——剪贴板写入与载荷生成属于阶段 2。
界面上有一行明确的文字说明，不会让人误以为它坏了。
"""

from __future__ import annotations

import datetime
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import aliases as alias_store
from . import clipboard, etupirka_db, exporters, paths, settings, vnite_payload
from . import progress as progress_store
from .etupirka_db import EtupirkaDbError
from .model import (
    FLAG_LABELS,
    FLAG_UNIDENTIFIED,
    Entry,
    LoadResult,
    format_duration,
)

WINDOW_TITLE = "Etupirka → Vnite 迁移助手"
MIN_WIDTH, MIN_HEIGHT = 900, 580

FILTER_ALL = "all"
FILTER_PENDING = "pending"
FILTER_UNIDENTIFIED = "unidentified"

FILTER_CHOICES: Tuple[Tuple[str, str], ...] = (
    (FILTER_ALL, "全部"),
    (FILTER_PENDING, "未迁移"),
    (FILTER_UNIDENTIFIED, "未识别"),
)

# 日文标题要能被渲染出来，按优先级挑一个系统里有的字体
FONT_CANDIDATES = (
    "Yu Gothic UI",
    "Meiryo",
    "MS UI Gothic",
    "Microsoft YaHei UI",
    "Segoe UI",
)

#: 程序目录里放这几个文件名之一即可换掉默认图标（docs §11 的默认约定）
ICON_CANDIDATES = ("etupirka2vnite.ico", "app.ico", "icon.ico")

#: ICO 文件头：保留位(2) + 类型 1=图标(2)
ICO_MAGIC = b"\x00\x00\x01\x00"

COLOR_ROW = "#ffffff"
COLOR_ROW_ALT = "#f6f7f9"
COLOR_ROW_SELECTED = "#d7e6f7"
COLOR_MUTED = "#666666"
COLOR_UNIDENTIFIED = "#b26a00"
COLOR_DONE = "#1a7f37"
COLOR_NOTE = "#8a6d3b"


def enable_dpi_awareness() -> None:
    """让界面在高 DPI 下不发虚。非 Windows 或调用失败时静默跳过。"""
    try:
        import ctypes
    except ImportError:
        return

    attempts = (
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
        lambda: ctypes.windll.user32.SetProcessDPIAware(),
    )
    for attempt in attempts:
        try:
            attempt()
            return
        except Exception:  # noqa: BLE001 - 纯粹是尽力而为
            continue


class MigratorApp:
    """主窗口。构造完即可用，不需要额外 init。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings: Dict[str, Any] = settings.load()
        self.result: Optional[LoadResult] = None
        self.entries: List[Entry] = []
        self.visible: List[Entry] = []
        self.selected: Optional[Entry] = None

        # 已迁移的 uid 集合，来自 progress.json
        self.progress_state: Dict[str, Any] = progress_store.load()
        self.migrated: Set[str] = progress_store.migrated_uids(self.progress_state)

        # 别名表：uid → 用户给这条记录起的名字
        self.alias_state: Dict[str, Any] = alias_store.load()
        self.aliases: Dict[str, str] = alias_store.mapping(self.alias_state)

        # uid -> (行容器, 该行所有需要换底色的控件, 基础底色)
        self._rows: Dict[str, Tuple[tk.Frame, List[tk.Widget], str]] = {}

        self._filter = tk.StringVar(value=FILTER_ALL)

        self._setup_window()
        self._setup_fonts()
        self._build_ui()
        self._apply_window_icon()
        self._install_exception_hook()
        self._refresh_source_label()
        self._update_status()
        self._autoload()

    # ------------------------------------------------------------------
    # 搭建
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

    def _setup_fonts(self) -> None:
        try:
            available = set(tkfont.families(self.root))
        except tk.TclError:
            return
        family = next((name for name in FONT_CANDIDATES if name in available), None)
        if not family:
            return
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                continue

    @staticmethod
    def _icon_search_dirs() -> List[Path]:
        """先找程序目录，再找 PyInstaller 的解包目录（打包后图标可能被打进去了）。"""
        dirs = [paths.app_dir()]
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            dirs.append(Path(bundle))
        return dirs

    @staticmethod
    def _looks_like_ico(path: Path) -> bool:
        """粗查 ICO 文件头。

        ``wm iconbitmap`` 拿到垃圾内容时**不会报错**，只会静默退化成默认图标，
        所以必须自己先挡一道，行为才是确定的。
        """
        try:
            with open(path, "rb") as handle:
                header = handle.read(6)
        except OSError:
            return False
        return (
            len(header) == 6
            and header[:4] == ICO_MAGIC
            and header[4:6] != b"\x00\x00"
        )

    def _apply_window_icon(self) -> None:
        """程序目录里放了 .ico 就用它，没有就保持 Tk 默认图标。

        刻意不往仓库里塞二进制图标：默认渲染已经够用，想换的人把 .ico 丢进
        程序目录即可，文件名见 :data:`ICON_CANDIDATES`。
        """
        self.icon_source: Optional[Path] = None
        for directory in self._icon_search_dirs():
            for name in ICON_CANDIDATES:
                candidate = directory / name
                if not candidate.is_file() or not self._looks_like_ico(candidate):
                    continue
                try:
                    self.root.iconbitmap(default=str(candidate))
                except tk.TclError:
                    continue  # 极少见：文件头像 ICO 但 Tk 仍拒绝
                self.icon_source = candidate
                return

    def _install_exception_hook(self) -> None:
        """未捕获的界面异常：落盘 + 弹窗，而不是静默打到 stderr。

        Tkinter 默认只把 traceback 打到 stderr——打包成 ``--windowed`` 之后没有
        控制台，用户就什么都看不到了。
        """

        def handle(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
            log_path: Optional[Path] = paths.error_log_file()
            try:
                with open(log_path, "a", encoding="utf-8") as handle_file:
                    handle_file.write("=" * 60 + "\n")
                    handle_file.write(
                        datetime.datetime.now().isoformat(timespec="seconds") + "\n"
                    )
                    traceback.print_exception(
                        exc_type, exc_value, exc_tb, file=handle_file
                    )
            except OSError:
                log_path = None

            detail = "".join(
                traceback.format_exception_only(exc_type, exc_value)
            ).strip()
            message = "界面遇到了一个未预期的错误：\n\n%s" % detail
            if log_path is not None:
                message += "\n\n详情已记录到：\n%s" % log_path
            try:
                messagebox.showerror("出错了", message, parent=self.root)
            except Exception:  # noqa: BLE001 - 兜底里再出错就只能放弃了
                pass

        self.root.report_callback_exception = handle

    def _build_ui(self) -> None:
        self._build_source_bar()
        self._build_list_area()
        self._build_detail_area()
        self._build_status_bar()
        self._build_context_menu()
        self.root.bind("<F5>", lambda _event: self.reload())
        self.root.bind_all("<Control-c>", self._on_ctrl_c)

    def _build_source_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="Etupirka 目录").grid(row=0, column=0, sticky="w")
        self.source_label = ttk.Label(bar, text="（未选择）", foreground=COLOR_MUTED)
        self.source_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        filters = ttk.Frame(bar)
        filters.grid(row=0, column=2, sticky="e")
        ttk.Label(filters, text="显示", foreground=COLOR_MUTED).pack(side="left", padx=(0, 6))
        for value, text in FILTER_CHOICES:
            ttk.Radiobutton(
                filters,
                text=text,
                value=value,
                variable=self._filter,
                command=self.apply_filter,
            ).pack(side="left")

        buttons = ttk.Frame(bar)
        buttons.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Button(buttons, text="选择目录…", command=self.choose_directory).pack(side="left")
        ttk.Button(buttons, text="选择 user.db…", command=self.choose_db_file).pack(
            side="left", padx=(6, 0)
        )

        self.recent_button = ttk.Menubutton(buttons, text="最近 ▾")
        self.recent_menu = tk.Menu(self.recent_button, tearoff=False)
        self.recent_button["menu"] = self.recent_menu
        self.recent_button.pack(side="left", padx=(6, 0))

        ttk.Button(buttons, text="重新读取", command=self.reload).pack(side="left", padx=(6, 0))

        self.export_button = ttk.Button(buttons, text="导出…", command=self.export_entries)
        self.export_button.pack(side="right")

    def _build_list_area(self) -> None:
        container = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self._list_container = container

        self.canvas = tk.Canvas(container, highlightthickness=0, background=COLOR_ROW)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.rows_frame = ttk.Frame(self.canvas)
        self._rows_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        self.empty_frame = ttk.Frame(container)
        self.empty_frame.grid(row=0, column=0, sticky="nsew")
        self.empty_message = ttk.Label(
            self.empty_frame,
            text="",
            justify="center",
            foreground=COLOR_MUTED,
            wraplength=520,
        )
        self.empty_message.pack(expand=True)
        ttk.Button(self.empty_frame, text="选择 Etupirka 目录…", command=self.choose_directory).pack(
            pady=(14, 0)
        )
        self._show_empty_panel()

    def _build_detail_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text="详情", padding=(12, 8))
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        frame.columnconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.detail_title = ttk.Label(header, text="（未选择条目）")
        self.detail_title.pack(side="left")
        self.copy_name_button = ttk.Button(
            header, text="复制名", width=8, state="disabled", command=self._copy_selected_name
        )
        self.copy_name_button.pack(side="left", padx=(10, 0))

        self.detail_meta = ttk.Label(frame, text="", foreground=COLOR_MUTED)
        self.detail_meta.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(frame, text="条目ID", foreground=COLOR_MUTED).grid(row=2, column=0, sticky="nw")
        self.detail_uid = ttk.Label(frame, text="—", foreground=COLOR_MUTED)
        self.detail_uid.grid(row=2, column=1, sticky="w", padx=(10, 0))

        ttk.Label(frame, text="启动路径", foreground=COLOR_MUTED).grid(
            row=3, column=0, sticky="nw", pady=(4, 0)
        )
        self.detail_path = ttk.Label(frame, text="—", wraplength=760, justify="left")
        self.detail_path.grid(row=3, column=1, sticky="w", pady=(4, 0), padx=(10, 0))

        ttk.Label(frame, text="标记", foreground=COLOR_MUTED).grid(row=4, column=0, sticky="nw")
        self.detail_flags = ttk.Label(frame, text="—", wraplength=760, justify="left")
        self.detail_flags.grid(row=4, column=1, sticky="w", padx=(10, 0))

    def _build_status_bar(self) -> None:
        self.status = ttk.Label(self.root, anchor="w", padding=(12, 8), foreground=COLOR_MUTED)
        self.status.grid(row=3, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # 滚动
    # ------------------------------------------------------------------

    def _on_rows_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._rows_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if not self.visible:
            return
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # 数据源
    # ------------------------------------------------------------------

    @staticmethod
    def _usable(target: str) -> bool:
        return etupirka_db.probe(target) == ""

    def _initial_dir(self) -> str:
        remembered = str(self.settings.get("db_path") or "")
        if remembered:
            candidate = Path(remembered)
            if candidate.is_dir():
                return str(candidate)
            if candidate.parent.is_dir():
                return str(candidate.parent)
        return str(Path.home())

    def choose_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="选择 Etupirka 所在的文件夹（里面有 user.db）",
            initialdir=self._initial_dir(),
        )
        if chosen:
            self.load_source(chosen)

    def choose_db_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择 user.db",
            initialdir=self._initial_dir(),
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")],
        )
        if chosen:
            self.load_source(chosen)

    def reload(self) -> None:
        remembered = str(self.settings.get("db_path") or "")
        if not remembered:
            self._show_empty("还没有选择数据源。\n请点上面的「选择目录…」。")
            return
        self.load_source(remembered)

    def load_source(self, target: str, notify: bool = True, keep_uid: str = "") -> bool:
        """校验并读取一个数据源。返回是否成功。"""
        problem = etupirka_db.probe(target)
        if not problem:
            try:
                result = etupirka_db.load_entries(target, aliases=self.aliases)
            except EtupirkaDbError as exc:  # 理论上 probe 已挡住，兜底
                problem = str(exc)
            else:
                self._adopt(target, result, keep_uid)
                return True

        self._show_empty(problem)
        if notify:
            messagebox.showerror("无法读取数据源", problem, parent=self.root)
        return False

    def _adopt(self, target: str, result: LoadResult, keep_uid: str = "") -> None:
        self.result = result
        self.entries = result.entries
        self.selected = None

        settings.remember_db(self.settings, target)
        settings.save(self.settings)
        self._refresh_source_label()

        self.apply_filter()

        # 重命名后会重新加载数据源，尽量把选中状态留在原来那条上
        again = next((item for item in self.visible if item.uid == keep_uid), None)
        if again is not None:
            self.select(again)
        else:
            self._clear_detail()

    def _autoload(self) -> None:
        """启动时的探测顺序：上次用的 → 程序自身所在目录 → 空状态。"""
        remembered = str(self.settings.get("db_path") or "")
        if remembered and self._usable(remembered):
            self.load_source(remembered, notify=False)
            return

        local = paths.find_local_user_db()
        if local is not None and self._usable(str(local.parent)):
            self.load_source(str(local.parent), notify=False)
            return

        hint = ""
        if remembered:
            hint = "\n\n上次使用的路径（%s）现在读不到了。" % remembered
        self._show_empty("请选择 Etupirka 的数据目录（或直接选 user.db 文件）。" + hint)

    def _refresh_source_label(self) -> None:
        remembered = str(self.settings.get("db_path") or "")
        self.source_label.configure(text=remembered or "（未选择）")
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.delete(0, "end")
        recent = [item for item in self.settings.get("recent", []) if item]
        if not recent:
            self.recent_menu.add_command(label="（还没有记录）", state="disabled")
            return
        for item in recent:
            self.recent_menu.add_command(label=item, command=lambda p=item: self.load_source(p))
        self.recent_menu.add_separator()
        self.recent_menu.add_command(label="清除记录", command=self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings["recent"] = []
        settings.save(self.settings)
        self._rebuild_recent_menu()

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def apply_filter(self) -> None:
        mode = self._filter.get()
        if mode == FILTER_UNIDENTIFIED:
            visible = [item for item in self.entries if item.has_flag(FLAG_UNIDENTIFIED)]
        elif mode == FILTER_PENDING:
            visible = [item for item in self.entries if item.uid not in self.migrated]
        else:
            visible = list(self.entries)

        self.visible = visible
        self._render_rows()
        self._update_status()

    def _show_rows(self) -> None:
        """显示列表，收起空状态面板。

        注意：``Canvas.tkraise`` 在 tkinter 里被别名成了 ``tag_raise``（抬升画布
        *图元*），拿它抬升控件会直接抛 TclError，所以这里一律用 grid 的显隐切换。
        """
        self.empty_frame.grid_remove()
        self.canvas.grid()
        self.scrollbar.grid()

    def _show_empty_panel(self) -> None:
        """显示空状态面板，收起列表。"""
        self.canvas.grid_remove()
        self.scrollbar.grid_remove()
        self.empty_frame.grid()

    def _render_rows(self) -> None:
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self._rows.clear()

        for index, entry in enumerate(self.visible):
            self._render_row(index, entry)

        if not self.visible:
            if not self.entries:
                self.empty_message.configure(text="这个数据源里没有游玩记录。")
            else:
                self.empty_message.configure(text="当前筛选条件下没有条目。")
            self._show_empty_panel()
            self.canvas.yview_moveto(0)
        else:
            self._show_rows()
            self.canvas.yview_moveto(0)

    def _render_row(self, index: int, entry: Entry) -> None:
        base = COLOR_ROW_ALT if index % 2 else COLOR_ROW
        row = tk.Frame(self.rows_frame, background=base, padx=10, pady=7)
        row.pack(fill="x")

        widgets: List[tk.Widget] = []

        dot = tk.Label(
            row,
            text=self._dot_text(entry),
            width=2,
            background=base,
            foreground=self._dot_color(entry),
        )
        dot.pack(side="left")
        widgets.append(dot)

        title = tk.Label(row, text=entry.label, anchor="w", background=base)
        title.pack(side="left", fill="x", expand=True, padx=(4, 10))
        widgets.append(title)

        hours = tk.Label(
            row, text="%.1f h" % (entry.total_seconds / 3600.0), width=8, anchor="e", background=base
        )
        hours.pack(side="left")
        widgets.append(hours)

        days = tk.Label(row, text="%d 天" % len(entry.days), width=6, anchor="e", background=base)
        days.pack(side="left")
        widgets.append(days)

        last = tk.Label(row, text=entry.last or "—", width=11, anchor="w", background=base)
        last.pack(side="left", padx=(10, 10))
        widgets.append(last)

        copy_button = ttk.Button(
            row, text="复制", width=6, command=lambda item=entry: self.copy_entry(item)
        )
        copy_button.pack(side="left")

        for widget in [row] + widgets:
            widget.bind("<Button-1>", lambda _event, item=entry: self.select(item))
            widget.bind("<Double-Button-1>", lambda _event, item=entry: self.copy_entry(item))
            widget.bind(
                "<Button-3>", lambda event, item=entry: self._show_context_menu(event, item)
            )
            widget.bind("<MouseWheel>", self._on_mousewheel)

        self._rows[entry.uid] = (row, widgets, base)

    def _dot_text(self, entry: Entry) -> str:
        if entry.uid in self.migrated:
            return "✓"
        return "⚠" if entry.has_flag(FLAG_UNIDENTIFIED) else "○"

    def _dot_color(self, entry: Entry) -> str:
        if entry.uid in self.migrated:
            return COLOR_DONE
        return COLOR_UNIDENTIFIED if entry.has_flag(FLAG_UNIDENTIFIED) else COLOR_MUTED

    def select(self, entry: Entry) -> None:
        self.selected = entry
        for uid, (row, widgets, base) in self._rows.items():
            background = COLOR_ROW_SELECTED if uid == entry.uid else base
            row.configure(background=background)
            for widget in widgets:
                widget.configure(background=background)
                if widget is widgets[0]:  # 圆点保留自己的前景色
                    continue
                widget.configure(foreground="#222222")
        self._update_detail(entry)

    def _clear_detail(self) -> None:
        self.detail_title.configure(text="（未选择条目）")
        self.detail_meta.configure(text="")
        self.detail_uid.configure(text="—")
        self.detail_path.configure(text="—")
        self.detail_flags.configure(text="—")
        self.copy_name_button.configure(state="disabled")
        self.selected = None

    def _update_detail(self, entry: Entry) -> None:
        self.detail_title.configure(text=entry.label)

        meta = [
            "时长 %s" % format_duration(entry.total_seconds),
            "%d 天有记录" % len(entry.days),
        ]
        if entry.days:
            meta.append("%s ~ %s" % (entry.first, entry.last))
        if entry.title_source == "user.db":
            meta.append("游戏名来自 user.db")
        elif entry.title_source == "alias":
            meta.append("游戏名来自别名表")
        self.detail_meta.configure(text=" · ".join(meta))

        self.detail_uid.configure(text=entry.uid)
        self.detail_path.configure(text=entry.exec_path or entry.proc_path or "—")

        # 「标记」只放需要留意的问题，信息来源归到上面那行
        labels = [FLAG_LABELS.get(flag, flag) for flag in entry.flags]
        text = "；".join(labels) if labels else "正常"
        if entry.has_flag(FLAG_UNIDENTIFIED):
            text += "（可右键「重命名为…」）"
        self.detail_flags.configure(text=text)

        self.copy_name_button.configure(state="normal")

    # ------------------------------------------------------------------
    # 复制与迁移状态
    # ------------------------------------------------------------------

    def _build_context_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制导入数据", command=lambda: self._context_action("copy"))
        menu.add_command(label="复制游戏名", command=lambda: self._context_action("copy_name"))
        menu.add_separator()
        menu.add_command(label="重命名为…", command=lambda: self._context_action("rename"))
        menu.add_command(label="查看原始 JSON", command=lambda: self._context_action("json"))
        menu.add_separator()
        menu.add_command(label="标记为已迁移", command=lambda: self._context_action("mark"))
        menu.add_command(label="标记为未迁移", command=lambda: self._context_action("unmark"))
        self.context_menu = menu

    def _show_context_menu(self, event: tk.Event, entry: Entry) -> None:
        self.select(entry)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _context_action(self, kind: str) -> None:
        entry = self.selected
        if entry is None:
            return
        if kind == "copy":
            self.copy_entry(entry)
        elif kind == "copy_name":
            self.copy_name(entry)
        elif kind == "rename":
            self.rename_entry(entry)
        elif kind == "json":
            self.show_payload(entry)
        elif kind == "mark":
            self._set_migrated(entry, True)
        elif kind == "unmark":
            self._set_migrated(entry, False)

    def copy_entry(self, entry: Entry) -> None:
        """生成载荷 → 自检 → 写剪贴板 → 记入迁移状态。"""
        payload_text, validation = vnite_payload.prepare(entry)
        if not validation.ok:
            messagebox.showerror(
                "这条记录无法导入",
                "数据没通过 Vnite 的校验规则，已阻止复制：\n\n%s" % validation.summary(),
                parent=self.root,
            )
            return

        try:
            clipboard.copy_text(payload_text)
        except clipboard.ClipboardError as exc:
            self._offer_manual_copy(entry, payload_text, str(exc))
            return

        progress_store.mark(self.progress_state, entry.uid)
        saved = progress_store.save(self.progress_state)
        self.migrated = progress_store.migrated_uids(self.progress_state)

        note = "已复制「%s」：%d 天 / %s" % (
            entry.label,
            len(entry.days),
            format_duration(entry.total_seconds),
        )
        if validation.warnings:
            note += "｜注意：" + validation.summary()
        if not saved:
            note += "｜迁移状态未能写入磁盘"

        if self._filter.get() == FILTER_PENDING:
            self.apply_filter()  # 这条会立刻从「未迁移」列表里消失
        else:
            self._refresh_row_state(entry)
            self.select(entry)
        self.status.configure(text=note)

    # ---- 复制游戏名 ----

    def _copy_selected_name(self) -> None:
        if self.selected is not None:
            self.copy_name(self.selected)

    def copy_name(self, entry: Entry) -> None:
        """只复制游戏名。

        刻意**不**改动迁移状态：那个状态的含义是「时长数据是否已经复制过」，
        把复制名字也算进去会让进度条失去意义。
        """
        name = entry.label
        if not name:
            return
        try:
            clipboard.copy_text(name)
        except clipboard.ClipboardError as exc:
            messagebox.showerror("复制失败", str(exc), parent=self.root)
            return
        self.status.configure(text="已复制游戏名「%s」" % name)

    def _on_ctrl_c(self, _event: tk.Event) -> Optional[str]:
        """Ctrl+C 复制选中条目的游戏名。

        焦点在输入类控件里时让它们自己处理（例如「原始 JSON」窗口里的全选复制）。
        """
        try:
            focused = self.root.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if isinstance(focused, (tk.Text, tk.Entry)):
            return None
        if self.selected is None:
            return None
        self.copy_name(self.selected)
        return "break"

    # ---- 重命名 ----

    def rename_entry(self, entry: Entry) -> None:
        current = alias_store.get(self.alias_state, entry.uid)
        initial = current or (entry.title if entry.identified else "")
        name = simpledialog.askstring(
            "重命名为…",
            "给「%s」起个名字：\n\n（留空并确定 = 清除别名，恢复自动命名）" % entry.label,
            initialvalue=initial,
            parent=self.root,
        )
        if name is None:  # 用户取消
            return

        alias_store.set_alias(self.alias_state, entry.uid, name)
        saved = alias_store.save(self.alias_state)
        self.aliases = alias_store.mapping(self.alias_state)

        cleaned = name.strip()
        note = (
            "已重命名为「%s」" % cleaned
            if cleaned
            else "已清除「%s」的别名" % entry.label
        )
        if not saved:
            note += "｜别名未能写入磁盘"

        remembered = str(self.settings.get("db_path") or "")
        if remembered:
            self.load_source(remembered, notify=False, keep_uid=entry.uid)
        self.status.configure(text=note)

    # ---- 导出 ----

    def export_entries(self) -> None:
        if self.result is None:
            messagebox.showinfo(
                "没有可导出的数据", "请先选择一个 Etupirka 数据源。", parent=self.root
            )
            return

        target = filedialog.askdirectory(
            title="选择导出目录", initialdir=self._export_initial_dir()
        )
        if not target:
            return

        try:
            written = exporters.export_all(
                target, self.result, aliases=self.aliases, migrated=self.migrated
            )
        except exporters.ExportError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return

        self.settings["export_dir"] = target
        settings.save(self.settings)
        self.status.configure(text="已导出 %d 个文件到 %s" % (len(written), target))
        messagebox.showinfo(
            "导出完成",
            "已导出 %d 个文件到：\n%s\n\n%s"
            % (len(written), target, "\n".join("· " + item.name for item in written)),
            parent=self.root,
        )

    def _export_initial_dir(self) -> str:
        remembered = str(self.settings.get("export_dir") or "")
        if remembered and Path(remembered).is_dir():
            return remembered
        fallback = paths.default_export_dir()
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return str(fallback)
        except OSError:
            return str(Path.home())

    def _set_migrated(self, entry: Entry, flag: bool) -> None:
        if flag:
            progress_store.mark(self.progress_state, entry.uid)
        else:
            progress_store.unmark(self.progress_state, entry.uid)
        saved = progress_store.save(self.progress_state)
        self.migrated = progress_store.migrated_uids(self.progress_state)

        if self._filter.get() == FILTER_PENDING:
            self.apply_filter()
        else:
            self._refresh_row_state(entry)

        note = "%s「%s」" % ("已标记" if flag else "已取消标记", entry.label)
        if not saved:
            note += "｜迁移状态未能写入磁盘"
        self.status.configure(text=note)

    def _refresh_row_state(self, entry: Entry) -> None:
        info = self._rows.get(entry.uid)
        if not info:
            return
        _row, widgets, _base = info
        widgets[0].configure(text=self._dot_text(entry), foreground=self._dot_color(entry))

    def show_payload(self, entry: Entry) -> None:
        """打开窗口显示原始 JSON，供人工复制。"""
        payload_text, validation = vnite_payload.prepare(entry)
        notes: List[str] = []
        if validation.errors:
            notes.append("⚠ 未通过 Vnite 校验：" + "；".join(validation.errors))
        if validation.warnings:
            notes.append("注意：" + "；".join(validation.warnings))
        self._show_payload_window(entry, payload_text, "\n".join(notes))

    def _offer_manual_copy(self, entry: Entry, payload_text: str, reason: str) -> None:
        messagebox.showwarning(
            "剪贴板不可用",
            "%s\n\n接下来打开一个窗口显示原始 JSON，你可以手动全选复制。" % reason,
            parent=self.root,
        )
        self._show_payload_window(entry, payload_text, reason)

    def _show_payload_window(self, entry: Entry, payload_text: str, note: str) -> None:
        window = tk.Toplevel(self.root)
        window.title("原始 JSON — %s" % entry.label)
        window.geometry("640x260")
        window.transient(self.root)

        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)

        if note:
            ttk.Label(
                frame, text=note, foreground=COLOR_NOTE, wraplength=600, justify="left"
            ).pack(anchor="w", pady=(0, 6))

        text = tk.Text(frame, wrap="char", height=6)
        text.pack(fill="both", expand=True)
        text.insert("1.0", payload_text)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))

        def select_all() -> None:
            text.tag_add("sel", "1.0", "end-1c")
            text.mark_set("insert", "1.0")
            text.focus_set()

        def retry() -> None:
            try:
                clipboard.copy_text(payload_text)
            except clipboard.ClipboardError as exc:
                messagebox.showerror("仍然失败", str(exc), parent=window)
                return
            window.destroy()
            self.status.configure(text="已复制「%s」的导入数据" % entry.label)

        ttk.Button(buttons, text="全选", command=select_all).pack(side="left")
        ttk.Button(buttons, text="重试复制", command=retry).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="关闭", command=window.destroy).pack(side="right")
        select_all()

    def _show_empty(self, message: str) -> None:
        self.result = None
        self.entries = []
        self.visible = []
        self._render_rows()
        self.empty_message.configure(text=message)
        self._show_empty_panel()
        self._clear_detail()

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------

    def _update_status(self) -> None:
        if self.result is None:
            self.status.configure(text="尚未选择数据源")
            return

        total = len(self.entries)
        migrated = sum(1 for item in self.entries if item.uid in self.migrated)
        unidentified = sum(1 for item in self.entries if item.has_flag(FLAG_UNIDENTIFIED))

        parts = ["已迁移 %d / %d 条" % (migrated, total)]
        parts.append("合计 %s" % format_duration(self.result.total_seconds))
        if unidentified:
            parts.append("%d 条未识别" % unidentified)
        if self.result.dropped:
            parts.append("%d 条无效记录已丢弃" % len(self.result.dropped))
        if self.result.warnings:
            parts.append("%d 条提醒" % len(self.result.warnings))
        if paths.uses_fallback_dir():
            parts.append("配置目录 %s" % paths.data_dir())
        self.status.configure(text=" · ".join(parts))


def main(argv: Optional[Sequence[str]] = None) -> int:
    enable_dpi_awareness()
    root = tk.Tk()
    MigratorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
