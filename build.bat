@echo off
setlocal
cd /d "%~dp0"

echo [1/3] 检查 PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo       未安装，正在通过 pip 安装...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 goto :fail
)

echo [2/3] 清理旧产物
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 打包
python -m PyInstaller etupirka2vnite.spec --noconfirm
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo 打包完成: dist\etupirka2vnite.exe
if exist etupirka2vnite.ico (
    echo 图标    : 已使用 etupirka2vnite.ico
) else (
    echo 图标    : 未提供 .ico，使用默认图标
    echo           ^(把一个 .ico 命名为 etupirka2vnite.ico 放进本目录，重跑即可^)
)
echo 自检    : dist\etupirka2vnite.exe --selfcheck
echo ============================================================
exit /b 0

:fail
echo.
echo 打包失败，请看上面的输出。
exit /b 1
