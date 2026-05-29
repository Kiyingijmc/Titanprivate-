@echo off
title TITAN AUTO-LAUNCHER
color 0B

echo ===================================================
echo   TITAN SYSTEM AUTO-START SEQUENCE
echo ===================================================
echo.

:: --- CONFIGURATION SECTION ---
:: UPDATE THIS PATH to point to your specific MetaTrader 5 terminal.exe
:: Common paths: "C:\Program Files\MetaTrader 5\terminal64.exe"
set "MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe"

:: --- AUDIT FIX: DYNAMIC ROOT PATH ---
:: Sets the working directory to the folder containing this script (%~dp0)
cd /d "%~dp0"

:: --- STEP 1: LAUNCH METATRADER 5 ---
echo [1/3] Checking MetaTrader 5...

if exist "%MT5_PATH%" (
    echo    Target Found: "%MT5_PATH%"
    echo    Launching /portable mode...
    start "" "%MT5_PATH%" /portable
) else (
    color 0E
    echo.
    echo [WARNING] MT5 Executable not found at configured path!
    echo Checked: "%MT5_PATH%"
    echo.
    echo Please edit 'AUTO_START.bat' and fix the MT5_PATH variable.
    echo Skipping MT5 launch, assuming it is already open...
    echo.
    :: We pause briefly to let user read the warning
    timeout /t 5
)

echo.
echo [WAIT] Waiting 120 seconds for Broker Connection and EA Loading...
echo.

:: --- STEP 2: SAFETY DELAY ---
:: Gives MT5 time to connect, load charts, and initialize ZMQ sockets.
:: Retained from original specification.
timeout /t 120 /nobreak

:: --- STEP 3: LAUNCH PYTHON BOT ---
echo.
echo [2/3] Launching Titan Logic Engine...

:: Check if the runner exists in the dynamic path
if exist "RUN_TITAN.bat" (
    call RUN_TITAN.bat
) else (
    color 0C
    echo [ERROR] Could not find RUN_TITAN.bat in the current directory!
    echo Current Dir: %CD%
    pause
)

exit