@echo off
cd /d "%~dp0"

rem === Pick Python interpreter ===
set "PYTHON_EXE="
set "PYW_EXE="
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py -3"
    set "PYW_EXE=pyw -3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        set "PYW_EXE=pythonw"
    )
)
if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found. Install Python 3.8+ and check "Add to PATH".
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

rem === Check core deps (use python with console so install errors are visible) ===
echo Checking dependencies...
%PYTHON_EXE% -c "import PyQt5, pygame, requests" >nul 2>&1
if errorlevel 1 (
    echo First run - installing dependencies...
    %PYTHON_EXE% -m pip install --upgrade pip
    %PYTHON_EXE% -m pip install PyQt5 pygame requests
    if errorlevel 1 (
        echo [ERROR] Failed to install deps. Run manually: pip install PyQt5 pygame requests
        pause
        exit /b 1
    )
)

rem === Launch GUI (pythonw has NO console window) ===
start "" %PYW_EXE% main.py
exit /b
