# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（单文件、无控制台）。

    python -m PyInstaller etupirka2vnite.spec --noconfirm

产出 ``dist/etupirka2vnite.exe``。程序目录里若存在 ``etupirka2vnite.ico``，
会自动用作 exe 图标；没有就用默认图标。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH).resolve()
ICON = PROJECT / "etupirka2vnite.ico"

a = Analysis(
    [str(PROJECT / "etupirka2vnite.py")],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=[],
    # 显式把 app 包整个收进来，免得以后新增模块时静态分析漏掉
    hiddenimports=collect_submodules("app"),
    hookspath=[],
    runtime_hooks=[],
    # 这些在运行时用不到，剔掉能显著减小体积
    excludes=[
        "unittest",
        "doctest",
        "pdb",
        "pydoc",
        "setuptools",
        "pip",
        "distutils",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="etupirka2vnite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
)
