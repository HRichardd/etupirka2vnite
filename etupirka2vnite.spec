# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir、无控制台）。

    python -m PyInstaller etupirka2vnite.spec --noconfirm

产出 ``dist/etupirka2vnite/`` 目录，入口是其中的 ``etupirka2vnite.exe``。
把整个目录一起分发（或用 ``build.bat`` 打成的 zip）。

**为什么用 onedir 而不是 onefile**：onefile 每次启动都要把自身解压到
``%TEMP%/_MEIxxxxxx``，实测在部分机器上会因解压被拦截而直接失败
（报 ``Failed to extract entry: VCRUNTIME140.dll.``），且启动明显更慢。
onedir 不做自解包，启动即时、不吃临时目录权限，分发时压成 zip 即可。

程序目录里若存在 ``etupirka2vnite.ico``，会自动用作 exe 图标；没有就用默认图标。
"""

from pathlib import Path
import re

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH).resolve()
ICON = PROJECT / "etupirka2vnite.ico"


def app_version():
    """从 app/__init__.py 读 __version__，作为唯一版本来源。

    用于 Windows 文件属性里的「文件版本 / 产品版本」，也用于 build.bat 的 zip 命名。
    """
    match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        (PROJECT / "app" / "__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise SystemExit("app/__init__.py 里找不到 __version__")
    return match.group(1)


VERSION = app_version()
# Windows 版本资源要 4 段数字，如 0.1.0 -> "0.1.0.0"
VERSION_4 = ".".join((VERSION.split(".") + ["0", "0", "0", "0"])[:4])


def write_version_file():
    """生成 PyInstaller 的版本资源文件，嵌入 exe 属性里的版本号。

    直接给 ``version=`` 传字符串会被当成文件路径，所以这里自己生成一个。
    写到 build/ 下（该目录是构建缓存，不提交）。
    """
    build_dir = PROJECT / "build"
    build_dir.mkdir(exist_ok=True)
    target = build_dir / "version_info.txt"
    target.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({VERSION_4.replace('.', ', ')}),
    prodvers=({VERSION_4.replace('.', ', ')}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileVersion', '{VERSION_4}'),
        StringStruct('ProductVersion', '{VERSION_4}'),
        StringStruct('ProductName', 'Etupirka -> Vnite \\u8fc1\\u79fb\\u52a9\\u624b'),
        StringStruct('FileDescription', 'Etupirka \\u2192 Vnite \\u8fc1\\u79fb\\u52a9\\u624b'),
        StringStruct('LegalCopyright', 'MIT License'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return str(target)


VERSION_FILE = write_version_file()

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
    [],
    exclude_binaries=True,
    name="etupirka2vnite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="etupirka2vnite",
)
