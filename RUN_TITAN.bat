@echo off
title TITAN ALGORITHMIC SYSTEM (INSTITUTIONAL)
color 0A

echo ========================================================
echo        TITAN ICT INSTITUTIONAL - STARTUP SEQUENCE
echo ========================================================
echo.

:: --- AUDIT FIX: DYNAMIC PATH RESOLUTION ---
:: %~dp0 refers to the Drive and Path of this script (0).
:: This allows the bot to run from ANY folder without hardcoding.
cd /d "%~dp0"

:: 0. Integrity Check (Environment)
if not exist .env (
    color 0C
    echo [CRITICAL] .env file missing! 
    echo Please create the .env file with your credentials before running.
    pause
    exit
)

:: 1. Check Python Availability
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found in PATH!
    echo Please install Python 3.10+ and add to PATH.
    pause
    exit
)

:: 2. Check Connection to Telegram
echo [CHECK] Testing Network and Telemetry...
:: Using 'python' instead of 'py' for broader compatibility
python test_telegram.py
if %ERRORLEVEL% NEQ 0 (
    color 0E
    echo.
    echo [WARNING] Telemetry Test Failed.
    echo The bot will attempt to start, but Alerts may be offline.
    echo Check your .env TELEGRAM_TOKEN and CHAT_ID.
    echo.
    timeout /t 5
) else (
    echo [PASS] Telemetry Online.
)
echo.

:: 3. Launch Main Brain
echo.
echo [START] IGNITING CORE ENGINE...
echo [INFO] Press CTRL+C to Shutdown safely.
echo.

:: AUDIT: Main Loop with Auto-Restart Capability could be added here,
:: but keeping strict single-run logic as per v14 spec.
python main.py

echo.
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo [CRASH] System exited with errors. Review logs above.
) else (
    echo [SHUTDOWN] System halted safely.
)
pause