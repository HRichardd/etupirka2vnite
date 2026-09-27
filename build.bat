@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [1/5] 检查 PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo       未安装，正在通过 pip 安装...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 goto :fail
)

echo [2/5] 清理旧产物
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

rem 版本号取自 app\__init__.py 的 __version__（唯一版本来源）
set "VERSION="
for /f "usebackq tokens=2 delims==" %%v in (`findstr /b /c:"__version__" app\__init__.py`) do set "VERSION=%%v"
set "VERSION=!VERSION: =!"
set "VERSION=!VERSION:"=!"
if "!VERSION!"=="" (
    echo       错误：读不到 app\__init__.py 里的 __version__
    goto :fail
)
echo       版本: !VERSION!

echo [3/5] 构建 onedir 版（文件夹，启动即时）
python -m PyInstaller etupirka2vnite.spec --noconfirm --distpath dist\onedir --workpath dist\.work-onedir
if errorlevel 1 goto :fail

echo [4/5] 构建 onefile 版（单文件，双击即用）
set "ETUPIRKA_ONEFILE=1"
python -m PyInstaller etupirka2vnite.spec --noconfirm --distpath dist\onefile --workpath dist\.work-onefile
set "ETUPIRKA_ONEFILE="
if errorlevel 1 goto :fail

set "ZIPDIR=etupirka2vnite-!VERSION!-win64.zip"
set "ZIPONE=etupirka2vnite-!VERSION!-win64-onefile.zip"

echo [5/5] 打包发布文件
powershell -NoProfile -Command "Compress-Archive -Path 'dist\onedir\etupirka2vnite' -DestinationPath ('dist\' + '!ZIPDIR!') -Force"
if errorlevel 1 goto :fail
if exist "dist\onefile\etupirka2vnite.exe" (
    powershell -NoProfile -Command "Copy-Item 'dist\onefile\etupirka2vnite.exe' ('dist\' + '!ZIPONE!') -Force"
    if errorlevel 1 goto :fail
)

rem 清掉 PyInstaller 的中间缓存，只留成品
if exist "dist\.work-onedir" rmdir /s /q "dist\.work-onedir"
if exist "dist\.work-onefile" rmdir /s /q "dist\.work-onefile"

echo.
echo ============================================================
echo 打包完成  版本 !VERSION!
echo.
echo   [A] 文件夹版（推荐，启动即时）
echo        程序目录 : dist\onedir\etupirka2vnite\
echo        入口     : dist\onedir\etupirka2vnite\etupirka2vnite.exe
echo        发布文件 : dist\!ZIPDIR!
echo.
echo   [B] 单文件版（简单，双击即用）
echo        发布文件 : dist\!ZIPONE!
if exist "dist\onefile\etupirka2vnite.exe" (
    echo        注意     : 单文件版每次启动会自解压到 %%TEMP%%，临时目录受限时可能启动失败
) else (
    echo        警告     : 单文件版未产出
)
echo.
if exist etupirka2vnite.ico (
    echo   图标     : 已使用 etupirka2vnite.ico
) else (
    echo   图标     : 未提供 .ico，使用默认图标
    echo              ^(把一个 .ico 命名为 etupirka2vnite.ico 放进本目录，重跑即可^)
)
echo ============================================================
exit /b 0

:fail
echo.
echo 打包失败，请看上面的输出。
exit /b 1
