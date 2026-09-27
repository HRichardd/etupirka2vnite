@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [1/4] 检查 PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo       未安装，正在通过 pip 安装...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 goto :fail
)

echo [2/4] 清理旧产物
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/4] 打包（onedir）
python -m PyInstaller etupirka2vnite.spec --noconfirm
if errorlevel 1 goto :fail

rem 版本号取自 app\__init__.py 的 __version__
set "VERSION="
for /f "usebackq tokens=2 delims==" %%v in (`findstr /b /c:"__version__" app\__init__.py`) do set "VERSION=%%v"
set "VERSION=!VERSION: =!"
set "VERSION=!VERSION:"=!"
if "!VERSION!"=="" set "VERSION=dev"

set "ZIPNAME=etupirka2vnite-!VERSION!-win64.zip"
echo [4/4] 压缩为 !ZIPNAME!
powershell -NoProfile -Command "Compress-Archive -Path 'dist\etupirka2vnite' -DestinationPath 'dist\!ZIPNAME!' -Force"
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo 打包完成
echo   程序目录 : dist\etupirka2vnite\  ^(整个目录一起分发^)
echo   入口     : dist\etupirka2vnite\etupirka2vnite.exe
echo   发布包   : dist\!ZIPNAME!
if exist etupirka2vnite.ico (
    echo   图标     : 已使用 etupirka2vnite.ico
) else (
    echo   图标     : 未提供 .ico，使用默认图标
    echo              ^(把一个 .ico 命名为 etupirka2vnite.ico 放进本目录，重跑即可^)
)
echo   自检     : dist\etupirka2vnite\etupirka2vnite.exe --selfcheck
echo ============================================================
exit /b 0

:fail
echo.
echo 打包失败，请看上面的输出。
exit /b 1
