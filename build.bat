@echo off
chcp 65001 >nul
rem 构建脚本：生成单文件 exe
rem 依赖：pip install pyinstaller   （运行程序本身只需标准库）
setlocal
cd /d "%~dp0"

echo [1/2] 检查 PyInstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo     未安装，正在安装 ...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo     安装失败。请确认 Python 已加入 PATH。
        pause
        exit /b 1
    )
)

echo [2/2] 开始打包 ...
python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "鼠标助手" ^
  --exclude-module numpy --exclude-module pandas --exclude-module PIL ^
  --exclude-module scipy --exclude-module matplotlib --exclude-module PyQt5 ^
  --exclude-module PySide2 --exclude-module PySide6 ^
  --exclude-module unittest --exclude-module email --exclude-module http ^
  --exclude-module xml --exclude-module pydoc --exclude-module doctest ^
  main.py

if errorlevel 1 (
    echo.
    echo 打包失败，请检查上面的错误信息。
    pause
    exit /b 1
)

echo.
echo 构建完成：dist\鼠标助手.exe
pause
endlocal