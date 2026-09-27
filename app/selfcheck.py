"""打包后的自检：把运行环境与关键路径写成一份报告。

**为什么需要这个**：exe 用 ``--windowed`` 打包，没有控制台，``print`` 无处可去；
而「配置文件到底落在 exe 旁边，还是落在 PyInstaller 的临时解包目录」正是 onefile
模式的经典坑（临时目录进程一退就没了）。所以自检把结果写进文件，由外部核对。

    etupirka2vnite.exe --selfcheck [--db <路径>] [--out <文件>]

退出码：0 正常；2 报告写不出去；3 配置目录不可写。
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import aliases, etupirka_db, paths, progress, settings

REPORT_NAME = "selfcheck.txt"
PROBE_NAME = ".selfcheck-probe"


def _probe_writable(directory: Path) -> tuple[bool, str]:
    probe = directory / PROBE_NAME
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)


def collect(db_target: str = "") -> Dict[str, Any]:
    """收集自检信息。任何一步失败都不抛异常，而是记进报告。"""
    report: Dict[str, Any] = {
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "frozen": paths.is_frozen(),
        "executable": sys.executable,
        "app_dir": str(paths.app_dir()),
        "data_dir": str(paths.data_dir()),
        "uses_fallback_dir": paths.uses_fallback_dir(),
        "files": {},
        "config": {},
        "source": {},
    }

    for label, path in (
        ("settings", paths.settings_file()),
        ("aliases", paths.aliases_file()),
        ("progress", paths.progress_file()),
        ("error_log", paths.error_log_file()),
    ):
        report["files"][label] = {
            "path": str(path),
            "exists": path.exists(),
            "next_to_executable": path.parent == paths.app_dir(),
        }

    writable, error = _probe_writable(paths.data_dir())
    report["data_dir_writable"] = writable
    if error:
        report["data_dir_error"] = error

    state = settings.load()
    alias_map = aliases.mapping(aliases.load())
    report["config"] = {
        "db_path": str(state.get("db_path") or ""),
        "recent": list(state.get("recent") or []),
        "aliases": len(alias_map),
        "migrated": len(progress.migrated_uids(progress.load())),
    }

    target = db_target or report["config"]["db_path"]
    if not target:
        local = paths.find_local_user_db()
        target = str(local.parent) if local is not None else ""

    if not target:
        report["source"] = {"checked": False, "reason": "没有可用的数据源"}
        return report

    problem = etupirka_db.probe(target)
    if problem:
        report["source"] = {
            "checked": True,
            "target": target,
            "ok": False,
            "error": problem,
        }
        return report

    result = etupirka_db.load_entries(target, aliases=alias_map)
    report["source"] = {
        "checked": True,
        "target": target,
        "ok": True,
        "resolved": str(result.path),
        "entry_count": len(result.entries),
        "total_seconds": result.total_seconds,
        "identified": result.identified_count,
        "unidentified": result.unidentified_count,
        "dropped": len(result.dropped),
    }
    return report


def render(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    add = lines.append

    add("Etupirka → Vnite 迁移助手 · 自检报告")
    add("=" * 56)
    add("时间           : %s" % report["checked_at"])
    add("打包运行       : %s" % report["frozen"])
    add("可执行文件     : %s" % report["executable"])
    add("程序目录       : %s" % report["app_dir"])
    add("配置目录       : %s" % report["data_dir"])
    add("回退到 APPDATA : %s" % report["uses_fallback_dir"])
    add("配置目录可写   : %s" % report["data_dir_writable"])
    if report.get("data_dir_error"):
        add("                 %s" % report["data_dir_error"])
    add("")

    add("== 配置文件 ==")
    for label, info in report["files"].items():
        add(
            "  %-10s %-6s 在程序目录旁=%s"
            % (label, "存在" if info["exists"] else "尚无", info["next_to_executable"])
        )
        add("             %s" % info["path"])
    add("")

    add("== 已记住的配置 ==")
    add("  数据源     : %s" % (report["config"]["db_path"] or "（未设置）"))
    add("  别名条数   : %d" % report["config"]["aliases"])
    add("  已迁移条数 : %d" % report["config"]["migrated"])
    add("")

    add("== 数据源读取 ==")
    source = report["source"]
    if not source.get("checked"):
        add("  跳过：%s" % source.get("reason", ""))
    elif not source.get("ok"):
        add("  失败：%s" % source.get("error"))
    else:
        add("  目标       : %s" % source["target"])
        add("  实际文件   : %s" % source["resolved"])
        add("  条目数     : %d" % source["entry_count"])
        add("  总时长     : %d 秒" % source["total_seconds"])
        add("  已识别     : %d" % source["identified"])
        add("  未识别     : %d" % source["unidentified"])
        add("  丢弃记录   : %d" % source["dropped"])

    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etupirka2vnite --selfcheck",
        description="把运行环境与关键路径写成一份报告文件（供打包后核对）。",
    )
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--db", default="", help="要检查的数据源；省略则用记住的或程序目录旁的 user.db")
    parser.add_argument("--out", default="", help="报告写到哪；默认写到程序目录下的 selfcheck.txt")
    args = parser.parse_args(argv)

    report = collect(args.db)
    target = Path(args.out) if args.out else paths.app_dir() / REPORT_NAME

    try:
        target.write_text(render(report), encoding="utf-8")
        target.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return 2

    return 0 if report.get("data_dir_writable") else 3
