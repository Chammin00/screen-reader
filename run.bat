@echo off
setlocal
title Kindle Voice Narrator
cd /d "%~dp0"

echo ========================================================
echo   Launching Kindle Voice Narrator and AI Study Companion
echo ========================================================

set PYTHONIOENCODING=utf-8

REM 1. Prefer user profile virtual environment (fully permitted by Device Guard / WDAC)
if exist "%USERPROFILE%\.antigravity_venvs\screen_reader\Scripts\python.exe" (
    echo Using authorized local environment: %USERPROFILE%\.antigravity_venvs\screen_reader
    "%USERPROFILE%\.antigravity_venvs\screen_reader\Scripts\python.exe" "%~dp0main.py"
    goto :check_exit
)

REM 2. Check project virtual environment directly
if exist "%~dp0.venv\Scripts\python.exe" (
    echo Using project environment: .venv
    "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
    goto :check_exit
)

REM 3. Look for uv package runner
set "UV_EXE="
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_EXE=%USERPROFILE%\.cargo\bin\uv.exe"
) else if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" (
    set "UV_EXE=%LOCALAPPDATA%\Programs\uv\uv.exe"
) else (
    for /f "delims=" %%I in ('where uv 2^>nul') do (
        if not defined UV_EXE set "UV_EXE=%%I"
    )
)

if defined UV_EXE (
    echo Using package runner: "%UV_EXE%"
    "%UV_EXE%" run python "%~dp0main.py"
    goto :check_exit
)

REM 3. Fallback to py launcher or system python
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Using Python Launcher (py)...
    py -3 "%~dp0main.py"
    goto :check_exit
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Using system python...
    python "%~dp0main.py"
    goto :check_exit
)

echo.
echo ========================================================
echo [ERROR] No suitable Python or uv installation was found!
echo Please ensure Python or uv is installed.
echo ========================================================
pause
exit /b 1

:check_exit
if %ERRORLEVEL% neq 0 (
    echo.
    echo ========================================================
    echo [Notice] Narrator exited with code %ERRORLEVEL%.
    echo ========================================================
    pause
)
