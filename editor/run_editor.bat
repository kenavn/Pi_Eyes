@echo off
REM Pi_Eyes Animatronics Studio Launcher (Windows)
REM Automatically sets up virtual environment and runs the editor

setlocal enabledelayedexpansion

echo Pi_Eyes Animatronics Studio Launcher
echo ====================================
echo.

REM Get script directory
set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%venv
set REQUIREMENTS=%SCRIPT_DIR%requirements.txt
set MAIN_SCRIPT=%SCRIPT_DIR%main.py

REM Check if Python 3 is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3 from https://www.python.org/
    pause
    exit /b 1
)

REM Check if requirements.txt exists
if not exist "%REQUIREMENTS%" (
    echo Error: requirements.txt not found at %REQUIREMENTS%
    pause
    exit /b 1
)

REM Check if main.py exists
if not exist "%MAIN_SCRIPT%" (
    echo Error: main.py not found at %MAIN_SCRIPT%
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    echo [92m✓ Virtual environment created[0m
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"

REM Install/update dependencies
REM Note: Windows doesn't have md5sum, so we'll check if .installed marker exists
set MARKER_FILE=%VENV_DIR%\.requirements_installed

if not exist "%MARKER_FILE%" (
    echo Installing dependencies...
    python -m pip install -q --upgrade pip
    python -m pip install -q -r "%REQUIREMENTS%"
    echo. > "%MARKER_FILE%"
    echo [92m✓ Dependencies installed[0m
    echo.
) else (
    echo [92m✓ Dependencies already installed[0m
    echo   (Delete %VENV_DIR% folder to reinstall)
    echo.
)

REM Check for game controller (silent check)
echo Checking for game controller...
python -c "import inputs; print('✓ Game controller detected' if inputs.devices.gamepads else '⚠ Warning: No game controller detected')" 2>nul
if errorlevel 1 (
    echo [93m⚠ Warning: Could not detect game controller[0m
    echo   Make sure your PS4 or Xbox controller is connected
)
echo.

REM Run the editor
echo Starting Animatronics Studio...
echo ====================================
echo.
python "%MAIN_SCRIPT%" %*

REM Deactivate virtual environment
call deactivate

pause
